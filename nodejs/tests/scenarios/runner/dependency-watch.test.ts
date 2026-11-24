import http from 'http'
import net, { AddressInfo } from 'net'

import { defaultConfig } from '~/common/config/config'

import { PROBE_TIMEOUT_MS, Probes, dependencyProbes, expectOk, failedProbes } from '../environment/stack'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { DependencyLoss, dependencyReasonOf, watchDependencies } from './dependency-watch'

const POSTGRES = defaultConfig.DATABASE_URL!
const UNREACHABLE_POSTGRES = 'postgres://posthog:posthog@127.0.0.1:1/posthog'
const VALKEY = { host: '127.0.0.1', port: 6379 }
const RUNNER_BLOCKS_MS = 2100

const busyFor = (ms: number): void => {
    const until = performance.now() + ms
    while (performance.now() < until) {}
}

const listening = async (server: net.Server): Promise<number> => {
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    return (server.address() as AddressInfo).port
}

const missingDatabase = (): string => {
    const url = new URL(POSTGRES)
    url.pathname = '/scenario_dependency_watch_missing'
    return url.toString()
}

describe('dependency watch', () => {
    let edge: ProviderEdge
    let silentPort: number
    let unavailableUrl: string
    const sockets: net.Socket[] = []
    const silent = net.createServer((socket) => sockets.push(socket))
    const unavailable = http.createServer((_request, response) => response.writeHead(503).end())

    beforeAll(async () => {
        edge = await startProviderEdge({ port: 0, trackingKeys: 'scenario-tracking-key' })
        silentPort = await listening(silent)
        unavailableUrl = `http://127.0.0.1:${await listening(unavailable)}`
    })

    afterAll(async () => {
        sockets.forEach((socket) => socket.destroy())
        silent.close()
        unavailable.close()
        await edge.close()
    })

    const edgeAndPostgres = (postgresUrl: string): Probes => {
        const { 'provider-edge': providerEdge, postgres } = dependencyProbes(edge.url, postgresUrl, VALKEY)
        return { 'provider-edge': providerEdge, postgres }
    }

    const watched = async (
        probes: Probes,
        runnerBlocksMs = 0
    ): Promise<{ losses: DependencyLoss[]; reason?: string }> => {
        const startedAt = Date.now()
        const saturating = runnerBlocksMs > 0 ? setInterval(() => busyFor(runnerBlocksMs), 5) : undefined
        try {
            const check = (): ReturnType<typeof failedProbes> => {
                const checking = failedProbes(probes)
                busyFor(runnerBlocksMs)
                return checking
            }
            const losses = await watchDependencies(check, 60_000).stop()
            const topStep = { scale: 320, startedAt, endedAt: startedAt + 120_000 }
            return { losses, reason: dependencyReasonOf(losses, [topStep]) }
        } finally {
            clearInterval(saturating)
        }
    }

    it('names a harness limit at the step when the runner is too busy to hear healthy dependencies', async () => {
        const { reason } = await watched(edgeAndPostgres(POSTGRES), RUNNER_BLOCKS_MS)

        expect(reason).toMatch(
            /^the runner's event loop was too busy to check provider-edge in the 320x step, postgres in the 320x step \(busy \d+% of the check\), a harness limit: the run cannot tell whether they stayed up$/
        )
    }, 30_000)

    it('names a dependency that went away while the runner was idle, with its step and error', async () => {
        const { reason } = await watched(edgeAndPostgres(UNREACHABLE_POSTGRES))

        expect(reason).toMatch(
            /^dependencies went away: postgres in the 320x step \(Postgres at 127\.0\.0\.1:1 failed: .*ECONNREFUSED.*\)$/
        )
    })

    it('names a harness limit when a busy Redis check runs out its budget without an answer', async () => {
        const silentValkey = dependencyProbes(edge.url, POSTGRES, { host: '127.0.0.1', port: silentPort })[
            'ses-rate-limiter-valkey'
        ]

        const { losses } = await watched({ 'ses-rate-limiter-valkey': silentValkey }, RUNNER_BLOCKS_MS)

        expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual(['ses-rate-limiter-valkey unheard'])
    }, 30_000)

    it.each([
        ['a refusal heard past its budget', () => edgeAndPostgres(UNREACHABLE_POSTGRES).postgres(), 2500],
        ['an HTTP status heard past its budget', () => expectOk(unavailableUrl), 2500],
        ['a Postgres server error heard past its budget', () => edgeAndPostgres(missingDatabase()).postgres(), 2500],
        ['an untyped error inside its budget', () => Promise.reject(new Error('not started')), 1500],
    ])(
        'names a dependency gone when its busy check fails with %s',
        async (_answer, probe, busyMs) => {
            const busyThenProbe = (): Promise<unknown> => {
                busyFor(busyMs)
                return probe()
            }

            const { losses } = await watched({ dependency: busyThenProbe })

            expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual(['dependency gone'])
        },
        30_000
    )

    const withCode = (code: string): Error => Object.assign(new Error(code), { code })

    it.each<[string, boolean, number, Error]>([
        ['an untyped error that its timer fired a little early', true, PROBE_TIMEOUT_MS - 5, new Error('timeout')],
        ['an untyped error well inside its timeout', false, PROBE_TIMEOUT_MS - 50, new Error('not started')],
        ['a refusal past its timeout', false, PROBE_TIMEOUT_MS, withCode('ECONNREFUSED')],
        ['a reset past its timeout', false, PROBE_TIMEOUT_MS, withCode('ECONNRESET')],
        ['an unknown host past its timeout', false, PROBE_TIMEOUT_MS, withCode('ENOTFOUND')],
        ['an unreachable host past its timeout', false, PROBE_TIMEOUT_MS, withCode('EHOSTUNREACH')],
        [
            'an error caused by a reset past its timeout',
            false,
            PROBE_TIMEOUT_MS,
            new Error('fetch failed', { cause: withCode('ECONNRESET') }),
        ],
    ])('counts %s as unanswered: %s', async (_error, unanswered, failsAfterMs, error) => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        try {
            const failing = (): Promise<unknown> =>
                new Promise((_resolve, reject) => setTimeout(() => reject(error), failsAfterMs))

            const checked = failedProbes({ dependency: failing })
            await jest.advanceTimersByTimeAsync(failsAfterMs)

            expect((await checked).map((failure) => failure.unanswered)).toEqual([unanswered])
        } finally {
            jest.useRealTimers()
        }
    })

    it('names a dependency gone when the retry hears a refusal after a busy first check timed out', async () => {
        const silentPostgres = edgeAndPostgres(`postgres://posthog:posthog@127.0.0.1:${silentPort}/posthog`).postgres
        const { postgres: refused } = edgeAndPostgres(UNREACHABLE_POSTGRES)
        let calls = 0
        const silentThenRefused = async (): Promise<unknown> => {
            if (++calls > 1) {
                return refused()
            }
            const saturating = setInterval(() => busyFor(RUNNER_BLOCKS_MS), 5)
            try {
                return await silentPostgres()
            } finally {
                clearInterval(saturating)
            }
        }

        const { losses } = await watched({ postgres: silentThenRefused })

        expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual(['postgres gone'])
    }, 30_000)

    it.each<[string, Record<string, number[]>, string[]]>([
        [
            'every dependency that first fails on a confirming check',
            { postgres: [1], redis: [2, 3], kafka: [3, 4] },
            ['postgres recovered', 'redis gone', 'kafka gone'],
        ],
        [
            'a dependency that fails again after it recovered',
            { postgres: [1, 3, 4], redis: [2] },
            ['postgres recovered', 'redis recovered', 'postgres gone'],
        ],
        [
            'two dependencies that flap out of step, at most twice each',
            { postgres: [1, 3, 5, 7, 9], redis: [2, 4, 6, 8, 10] },
            ['postgres recovered', 'redis recovered', 'postgres recovered', 'redis recovered'],
        ],
    ])('confirms %s before the watch stops', async (_case, failingChecks, expected) => {
        const failingOn = (failing: number[]): (() => Promise<unknown>) => {
            let calls = 0
            return () =>
                failing.includes(++calls) ? Promise.reject(new Error('connect ECONNREFUSED')) : Promise.resolve()
        }
        const probes = Object.fromEntries(
            Object.entries(failingChecks).map(([name, failing]) => [name, failingOn(failing)])
        )

        const { losses } = await watched(probes)

        expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual(expected)
    })

    it('names each unheard dependency at its own ramp step', () => {
        const steps = [
            { scale: 2, startedAt: 0, endedAt: 1000 },
            { scale: 320, startedAt: 1000, endedAt: 2000 },
        ]
        const unheard = (name: string, at: number): DependencyLoss => ({
            name,
            at,
            reason: 'timeout expired',
            runnerBusy: 0.9,
            kind: 'unheard',
        })

        expect(dependencyReasonOf([unheard('provider-edge', 500), unheard('postgres', 1500)], steps)).toMatch(
            /^the runner's event loop was too busy to check provider-edge in the 2x step, postgres in the 320x step /
        )
    })

    it('keeps a dependency that failed once and answered the next probe as evidence, not as a loss', async () => {
        let answered = 0
        const blip = http.createServer((_request, response) => response.writeHead(answered++ === 0 ? 503 : 200).end())
        await new Promise<void>((resolve) => blip.listen(0, '127.0.0.1', resolve))
        try {
            const { port } = blip.address() as AddressInfo

            const { losses, reason } = await watched({ personhog: () => expectOk(`http://127.0.0.1:${port}`) })

            expect({ reason, kinds: losses.map(({ name, kind }) => `${name} ${kind}`) }).toEqual({
                reason: undefined,
                kinds: ['personhog recovered'],
            })
        } finally {
            blip.close()
        }
    })
})
