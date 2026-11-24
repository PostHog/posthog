import http from 'http'
import { AddressInfo } from 'net'

import { defaultConfig } from '~/common/config/config'

import { Probes, dependencyProbes, expectOk, failedProbes } from '../environment/stack'
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

describe('dependency watch', () => {
    let edge: ProviderEdge

    beforeAll(async () => {
        edge = await startProviderEdge({ port: 0, trackingKeys: 'scenario-tracking-key' })
    })

    afterAll(() => edge.close())

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
            const losses = await watchDependencies(() => failedProbes(probes), 60_000).stop()
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

    it('names a refused dependency gone even when the busy runner hears the refusal after the timeout', async () => {
        const { postgres } = edgeAndPostgres(UNREACHABLE_POSTGRES)
        const heardLate = (): Promise<unknown> => {
            busyFor(1500)
            const refused = postgres()
            busyFor(1000)
            return refused
        }

        const { reason } = await watched({ postgres: heardLate })

        expect(reason).toMatch(/^dependencies went away: postgres in the 320x step \(.*ECONNREFUSED.*\)$/)
    }, 30_000)

    it('names a dependency gone when the retry hears a refusal after a busy first check timed out', async () => {
        let calls = 0
        const silentThenRefused = (): Promise<unknown> => {
            if (++calls === 1) {
                busyFor(1500)
                return Promise.reject(new Error('timeout expired'))
            }
            return Promise.reject(new Error('connect ECONNREFUSED'))
        }

        const { losses } = await watched({ postgres: silentThenRefused })

        expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual(['postgres gone'])
    }, 30_000)

    it('confirms every dependency that first fails on a confirming check before the watch stops', async () => {
        const failingOn = (failing: number[]): (() => Promise<unknown>) => {
            let calls = 0
            return () =>
                failing.includes(++calls) ? Promise.reject(new Error('connect ECONNREFUSED')) : Promise.resolve()
        }

        const { losses } = await watched({
            postgres: failingOn([1]),
            redis: failingOn([2, 3]),
            kafka: failingOn([3, 4]),
        })

        expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual([
            'postgres recovered',
            'redis gone',
            'kafka gone',
        ])
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
