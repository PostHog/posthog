import { execFile } from 'child_process'
import { readFileSync } from 'fs'
import http from 'http'
import net, { AddressInfo } from 'net'
import path from 'path'
import { pathToFileURL } from 'url'
import { promisify } from 'util'

import { defaultConfig } from '~/common/config/config'

import { startProbeProcess } from '../environment/probe-process'
import { PROBE_TIMEOUT_MS, ProbeFailure, Probes, dependencyProbes, expectOk, failedProbes } from '../environment/stack'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { DependencyLoss, dependencyReasonOf, watchDependencies } from './dependency-watch'

const POSTGRES = defaultConfig.DATABASE_URL!
const UNREACHABLE_POSTGRES = 'postgres://posthog:posthog@127.0.0.1:1/posthog'
const VALKEY = { host: '127.0.0.1', port: 6379 }
const RUNNER_BLOCKS_MS = 2100
const HELD_SOCKETS = 200
const TSX = pathToFileURL(require.resolve('tsx')).href

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

    const watching = async (
        failing: () => Promise<ProbeFailure[]>,
        runnerBlocksMs = 0
    ): Promise<{ losses: DependencyLoss[]; reason?: string }> => {
        const startedAt = Date.now()
        const saturating = runnerBlocksMs > 0 ? setInterval(() => busyFor(runnerBlocksMs), 5) : undefined
        try {
            const check = (): Promise<ProbeFailure[]> => {
                const checking = failing()
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

    const watched = (probes: Probes, runnerBlocksMs = 0): ReturnType<typeof watching> =>
        watching(() => failedProbes(probes), runnerBlocksMs)

    const watchedFromProcess = async (
        edgeUrl: string,
        postgresUrl: string,
        runnerBlocksMs = 0
    ): ReturnType<typeof watching> => {
        const probes = startProbeProcess({
            edgeUrl,
            postgresUrl,
            sesValkey: VALKEY,
            only: ['provider-edge', 'postgres'],
        })
        try {
            return await watching(() => probes.check(), runnerBlocksMs)
        } finally {
            probes.close()
        }
    }

    it('hears Postgres from its own process, and the edge the busy runner hosts as unheard, not gone', async () => {
        const { losses } = await watchedFromProcess(edge.url, POSTGRES, RUNNER_BLOCKS_MS)

        expect(losses.map(({ name, kind }) => `${name} ${kind}`)).toEqual(['provider-edge unheard'])
    }, 30_000)

    it('names dependencies that went away from its own process, with their step and error', async () => {
        const { reason } = await watchedFromProcess(unavailableUrl, UNREACHABLE_POSTGRES)

        expect(reason).toMatch(
            /^dependencies went away: postgres in the 320x step \(Postgres at 127\.0\.0\.1:1 failed: .*ECONNREFUSED.*\), provider-edge in the 320x step \(http:\/\/127\.0\.0\.1:\d+\/_health answered 503\)$/
        )
    }, 30_000)

    it('checks the provider edge over one kept-alive connection', async () => {
        let connections = 0
        const healthy = http.createServer((_request, response) => response.writeHead(200).end())
        healthy.on('connection', () => connections++)
        const probes = startProbeProcess({
            edgeUrl: `http://127.0.0.1:${await listening(healthy)}`,
            postgresUrl: POSTGRES,
            sesValkey: VALKEY,
            only: ['provider-edge'],
        })
        try {
            const failures = [await probes.check(), await probes.check()]

            expect({ failures, connections }).toEqual({ failures: [[], []], connections: 1 })
        } finally {
            probes.close()
            healthy.close()
        }
    }, 30_000)

    it('keeps the dependency credentials off the command line of its probe process', async () => {
        const postgresUrl = 'postgres://posthog:scenario-probe-secret@127.0.0.1:1/posthog'
        const probes = startProbeProcess({ edgeUrl: undefined, postgresUrl, sesValkey: VALKEY, only: [] })
        try {
            await expect(probes.check()).resolves.toEqual([])

            expect(readFileSync(`/proc/${probes.pid}/cmdline`, 'utf8')).not.toContain('scenario-probe-secret')
        } finally {
            probes.close()
        }
    }, 30_000)

    it('names a harness limit when the run host has no file descriptor left to start the probe process', async () => {
        const watch = `
            const { openSync } = require('fs')
            const { startProbeProcess } = require(${JSON.stringify(require.resolve('../environment/probe-process'))})
            const { watchDependencies, dependencyReasonOf } = require(${JSON.stringify(require.resolve('./dependency-watch'))})
            const probes = startProbeProcess({ edgeUrl: undefined, postgresUrl: '', sesValkey: { host: '', port: 0 } })
            try {
                for (;;) openSync('/dev/null', 'r')
            } catch {}
            watchDependencies(() => probes.check(), 60_000)
                .stop()
                .then((losses) => process.stdout.write(dependencyReasonOf(losses, []) ?? 'no loss', () => process.exit(0)))
        `
        const { stdout } = await promisify(execFile)(
            'bash',
            ['-c', 'ulimit -n 256 && exec "$0" --import "$1" -e "$2"', process.execPath, TSX, watch],
            { cwd: path.join(__dirname, '../../..') }
        )

        expect(stdout).toMatch(
            /^the run host ran out of file descriptors to check health check at \S+ \(the probe process failed: spawn \S+ EMFILE\), a harness limit/
        )
    }, 30_000)

    it('names a harness limit when the run host has no local port left to check a dependency', async () => {
        const noPort = Object.assign(new Error('connect EADDRNOTAVAIL 127.0.0.1:4566 - Local (0.0.0.0:0)'), {
            code: 'EADDRNOTAVAIL',
        })

        const held = await Promise.all(
            Array.from({ length: HELD_SOCKETS }, async () => {
                const socket = net.connect(silentPort, '127.0.0.1')
                await new Promise((resolve) => socket.once('connect', resolve))
                return socket
            })
        )
        try {
            const { losses, reason } = await watched({ 'provider-edge': () => Promise.reject(noPort) })

            expect({ reason, held: losses[0].sockets?.[`ESTAB 127.0.0.1:${silentPort}`] }).toEqual({
                reason: 'the run host ran out of local ports to check provider-edge in the 320x step (connect EADDRNOTAVAIL 127.0.0.1:4566 - Local (0.0.0.0:0)), a harness limit: the run cannot tell whether it stayed up',
                held: HELD_SOCKETS,
            })
        } finally {
            held.forEach((socket) => socket.destroy())
        }
    })

    const NO_PORT = 'connect EADDRNOTAVAIL 127.0.0.1:4566 - Local (0.0.0.0:0)'
    const REFUSED = 'connect ECONNREFUSED 127.0.0.1:4566'

    const HELD = { 'ESTAB 127.0.0.1:9': 3 }
    const noPort = (sockets?: Record<string, number>): ProbeFailure => ({
        name: 'provider-edge',
        reason: NO_PORT,
        unanswered: false,
        hostLimit: 'local ports',
        ...(sockets ? { sockets } : {}),
    })
    const refused: ProbeFailure = { name: 'provider-edge', reason: REFUSED, unanswered: false }
    const timedOut: ProbeFailure = {
        name: 'provider-edge',
        reason: 'connect to 127.0.0.1:4566 timed out',
        unanswered: true,
    }
    const exited = new Error('the probe process exited with SIGKILL')
    const hostLimitReason = `the run host ran out of local ports to check provider-edge in the 320x step (${NO_PORT}), a harness limit: the run cannot tell whether it stayed up`

    it.each([
        {
            title: 'the host limit, not the timeout of its busy confirming check',
            attempts: [[noPort(HELD)], [timedOut]],
            expected: { reason: hostLimitReason, sockets: HELD },
        },
        {
            title: 'the refusal of a dependency that went away, not the host limit of its confirming check',
            attempts: [[refused], [noPort()]],
            expected: {
                reason: `dependencies went away: provider-edge in the 320x step (${REFUSED})`,
                sockets: undefined,
            },
        },
        {
            title: 'the sockets of the first check when the confirming check hit the limit without them',
            attempts: [[noPort(HELD)], [noPort()]],
            expected: { reason: hostLimitReason, sockets: HELD },
        },
        {
            title: 'the refusal, never a recovery, when the probe process failed on the confirming check',
            attempts: [[refused], exited, []],
            expected: {
                reason: `dependencies went away: provider-edge in the 320x step (${REFUSED})`,
                sockets: undefined,
            },
        },
        {
            title: 'the busy timeout, never a loss, when the probe process failed on a quiet confirming check',
            attempts: [[timedOut], exited, []],
            expected: {
                reason: expect.stringMatching(
                    /^the runner's event loop was too busy to check provider-edge in the 320x step \(busy \d+% of the check\)/
                ),
                sockets: undefined,
            },
        },
    ])('quotes $title', async ({ attempts, expected }) => {
        const scripted: (ProbeFailure[] | Error)[] = [...attempts]
        // A probe check keeps the runner busy, and a failed probe process leaves it idle until the failure arrives.
        const next = async (): Promise<ProbeFailure[]> => {
            const attempt = scripted.shift() ?? []
            if (attempt instanceof Error) {
                await new Promise((resolve) => setTimeout(resolve, 50))
                throw attempt
            }
            busyFor(200)
            return attempt
        }

        const { losses, reason } = await watching(next)

        expect({ reason, sockets: losses.find(({ name }) => name === 'provider-edge')?.sockets }).toEqual(expected)
    })

    it('keeps a probe process whose answer waited while the runner was blocked past the deadline', async () => {
        const probes = startProbeProcess(
            { edgeUrl: edge.url, postgresUrl: POSTGRES, sesValkey: VALKEY, only: ['postgres'] },
            5_000
        )
        try {
            await expect(probes.check()).resolves.toEqual([])
            const answering = probes.pid

            const checking = probes.check()
            busyFor(6_000)

            await expect(checking).resolves.toEqual([])
            expect(probes.pid).toEqual(answering)
        } finally {
            probes.close()
        }
    }, 30_000)

    it.each([
        ['stopped answering', false, 'the probe process did not answer within 8000 ms'],
        ['exited during a check', true, 'the probe process exited with SIGKILL'],
    ])(
        'answers from a fresh probe process after the last one %s',
        async (_how, exits, failure) => {
            const probes = startProbeProcess(
                { edgeUrl: edge.url, postgresUrl: POSTGRES, sesValkey: VALKEY, only: ['provider-edge'] },
                8_000
            )
            try {
                await expect(probes.check()).resolves.toEqual([])
                const stuck = probes.pid!
                process.kill(stuck, 'SIGSTOP')
                const checking = probes.check()
                if (exits) {
                    process.kill(stuck, 'SIGKILL')
                }

                await expect(checking).rejects.toThrow(failure)
                await expect(probes.check()).resolves.toEqual([])
                expect(probes.pid).not.toEqual(stuck)
            } finally {
                probes.close()
            }
        },
        40_000
    )

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
