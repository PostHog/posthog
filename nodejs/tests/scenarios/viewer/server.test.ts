import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'fs'
import { Server, createServer } from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { waitForExpect } from '../../helpers/expectations'
import type { MetricSample } from '../judge/measurements'
import { LIVE_FILE, openLiveLog } from '../runner/live'
import { liveOf } from './live'
import { createViewerServer } from './server'

const RUN_ID = '0b5e7f3a-1c2d-4e5f-8a9b-0c1d2e3f4a5b'
const UNFINISHED_RUN_ID = '9a8b7c6d-5e4f-4a3b-9c2d-1e0f9a8b7c6d'
const LIVE_RUN_ID = '5d4c3b2a-1f0e-4d9c-8b7a-6f5e4d3c2b1a'
const DRIVE_START = Date.parse('2026-01-05T10:00:00.000Z')
const at = (seconds: number): number => DRIVE_START + seconds * 1000
const iso = (seconds: number): string => new Date(at(seconds)).toISOString()

const sample = (
    seconds: number,
    cpuSeconds: number,
    processed: number,
    startedAt = at(-60) / 1000,
    role = 'cdp-cyclotron-worker-email'
): MetricSample => ({
    role,
    replica: 0,
    at: at(seconds),
    startedAt,
    cpuSeconds,
    rssBytes: 100 * 1024 * 1024,
    processed: { email: processed },
    pgClientErrors: 0,
    consumerLoopErrors: 0,
    janitorStalled: 0,
    lateness: {},
})

function writeRun(stateDir: string): void {
    const dir = path.join(stateDir, RUN_ID)
    mkdirSync(dir, { recursive: true })
    const write = (name: string, value: unknown): void => writeFileSync(path.join(dir, name), JSON.stringify(value))
    write('scorecard.json', {
        runId: RUN_ID,
        cardId: 'email-worker-killed',
        status: 'passed',
        statusReason: 'every invariant held',
        origin: 'local-agent',
        startedAt: iso(-30),
        endedAt: iso(60),
        units: { targetUnits: 4, offeredUnits: 4 },
        convergence: { converged: true, unfinishedJobs: 0, unrecorded: [], tookMs: 9000 },
        invariants: [{ name: 'at_least_once', passed: true, observed: 0, unitIds: [] }],
        measurements: [],
        admissions: [],
        bars: [],
        timeline: [
            {
                valve: 'role.kill',
                target: 'cdp-cyclotron-worker-email',
                requestedAt: iso(9),
                appliedAt: iso(10),
                observedAt: iso(10),
                releasedAt: iso(11),
            },
        ],
        evidenceDir: dir,
        event: { head_sha: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00', head_dirty: false, profile_name: 'synthetic' },
    })
    write('metrics.json', {
        samples: [
            sample(0, 10, 100),
            sample(5, 12, 150),
            sample(10, 13, 200),
            sample(15, 0.5, 5, at(12) / 1000),
            sample(20, 1.5, 30, at(12) / 1000),
            ...[
                [0, 0, 0],
                [1, 0.5, 2],
                [4, 2, 8],
                [13, 6.5, 26],
            ].map(([seconds, cpuSeconds, processed]) =>
                sample(seconds, cpuSeconds, processed, at(-60) / 1000, 'cdp-cyclotron-worker-hogflow')
            ),
        ],
        missed: [],
        host: [],
    })
    write('probes.json', {
        drive: { startedAt: at(0), endedAt: at(30) },
        writer: [{ at: at(1), monoMs: 1, ok: true, latencyMs: 3 }],
        queue: [
            { at: at(5), due: 7, running: 2, oldestDueSeconds: 1.5, inserted: 10 },
            { at: at(10), error: 'connection terminated' },
        ],
    })
    write('journal.json', [
        {
            unitId: 'u-1',
            kind: 'event',
            teamId: 1,
            offeredAt: at(1),
            answer: { accepted: true },
            expect: { deliveries: ['email'] },
        },
        {
            unitId: 'u-2',
            kind: 'transactional',
            teamId: 1,
            offeredAt: at(2),
            answer: { accepted: false, status: 503 },
            expect: { deliveries: [] },
        },
    ])
    write('truth.json', [
        {
            seq: 1,
            at: iso(3),
            kind: 'ses.send',
            unitId: 'u-1',
            actionId: 'email',
            status: 400,
            fault: 'ses.reject',
            detail: {},
        },
        { seq: 2, at: iso(4), kind: 'ses.send', unitId: 'u-1', actionId: 'email', status: 200, detail: {} },
        { seq: 3, at: iso(4), kind: 'ses.send', unitId: 'u-1', actionId: 'email', status: 200, detail: {} },
        {
            seq: 4,
            at: iso(6),
            kind: 'webhook',
            unitId: 'u-1',
            actionId: 'hook',
            status: 503,
            fault: 'dest.status',
            detail: {},
        },
        { seq: 5, at: iso(7), kind: 'ses.feedback', status: 200, detail: {} },
    ])
    mkdirSync(path.join(stateDir, UNFINISHED_RUN_ID))
}

function writeCards(cardsDir: string): void {
    const write = (name: string, lines: string[]): void =>
        writeFileSync(path.join(cardsDir, `${name}.yaml`), `${lines.join('\n')}\n`)
    const common = (id: string, drive: string[]): string[] => [
        `id: ${id}`,
        'version: 3',
        'clock: real',
        'profile: synthetic',
        'seed: 11',
        'setup:',
        '    teams: 2',
        'drive:',
        ...drive,
        'convergeWithin: 1m',
        'invariants:',
        '    - name: at_least_once',
        '    - name: duplicate_sends',
        'gates:',
        '    duplicate_sends: 0',
        'measure:',
        '    - name: delivery_latency_ms',
    ]
    write('frozen-worker', [
        ...common('frozen-worker', ['    for: 40s', '    traffic:', '        - name: event_webhook']),
        'valves:',
        '    - valve: role.freeze',
        '      target: cdp-cyclotron-worker-hogflow',
        '      dose: {}',
        '      when:',
        '          name: running_on_queue',
        '          params:',
        '              queue: hogflow',
        '              atLeast: 2',
        '      for: 20s',
    ])
    write('ramp', [
        ...common('ramp', [
            '    for: 3m',
            '    traffic:',
            '        - name: event_email',
            '    ramp:',
            '        - scale: 1',
            '          for: 1m',
            '        - scale: 3',
            '          for: 2m',
        ]),
        'bars:',
        '    - name: writer_cpu_under',
        '      params:',
        '          percent: 60',
    ])
    write('failover', [
        ...common('failover', ['    for: 40s', '    traffic:', '        - name: event_webhook']),
        'valves:',
        '    - valve: pg.failover',
        '      target: cyclotron',
        '      dose: {}',
        '      at: 10s',
        '      for: 20s',
    ])
    write('broken', ['id: broken', 'version: one'])
}

describe('scenario viewer', () => {
    let stateDir: string
    let cardsDir: string
    let server: Server
    let base: string

    const get = async (route: string): Promise<{ status: number; body: any }> => {
        const response = await internalFetch(`${base}${route}`)
        return { status: response.status, body: parseJSON(await response.text()) }
    }

    beforeAll(async () => {
        stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-viewer-'))
        writeRun(stateDir)
        cardsDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-viewer-cards-'))
        writeCards(cardsDir)
        server = createViewerServer({ stateDir, cardsDir })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterAll(async () => {
        await new Promise((resolve) => server.close(resolve))
        rmSync(stateDir, { recursive: true, force: true })
        rmSync(cardsDir, { recursive: true, force: true })
    })

    it('lists only runs that wrote a scorecard', async () => {
        const { body } = await get('/api/runs')

        expect(body).toEqual([
            expect.objectContaining({
                runId: RUN_ID,
                cardId: 'email-worker-killed',
                status: 'passed',
                durationS: 90,
                converged: true,
                headSha: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00',
                valves: [{ valve: 'role.kill', target: 'cdp-cyclotron-worker-email' }],
                where: 'local',
            }),
        ])
    })

    it('turns a run’s evidence into rates that skip a restart, hold through uneven scrapes, and latency to the first clean delivery', async () => {
        const { status, body } = await get(`/api/runs/${RUN_ID}`)

        expect(status).toBe(200)
        expect(body.drive).toEqual({ startedAt: at(0), endedAt: at(30) })
        expect(body.series.roles).toEqual([
            {
                role: 'cdp-cyclotron-worker-email',
                replicas: 1,
                restarts: [at(12)],
                points: [
                    { at: at(0), cpuPercent: 40, processedPerSecond: 10, rssMb: 100 },
                    { at: at(5), cpuPercent: 20, processedPerSecond: 10, rssMb: 100 },
                    { at: at(15), cpuPercent: 20, processedPerSecond: 5, rssMb: 100 },
                ],
            },
            {
                role: 'cdp-cyclotron-worker-hogflow',
                replicas: 1,
                restarts: [],
                points: [
                    { at: at(0), cpuPercent: 50, processedPerSecond: 2, rssMb: 100 },
                    { at: at(5), cpuPercent: 50, processedPerSecond: 2, rssMb: 100 },
                    { at: at(10), cpuPercent: 50, processedPerSecond: 2, rssMb: 100 },
                ],
            },
        ])
        expect(body.series.queue).toEqual([{ at: at(5), due: 7, running: 2, oldestDueSeconds: 1.5 }])
        expect(body.series.flow).toEqual([
            {
                at: at(0),
                offeredEvents: 1,
                offeredTransactional: 1,
                refused: 1,
                emailOk: 2,
                emailFaulted: 1,
                webhookOk: 0,
                webhookFaulted: 0,
                feedback: 0,
                latencyP50Ms: 3000,
                latencyP95Ms: 3000,
            },
            {
                at: at(5),
                offeredEvents: 0,
                offeredTransactional: 0,
                refused: 0,
                emailOk: 0,
                emailFaulted: 0,
                webhookOk: 0,
                webhookFaulted: 1,
                feedback: 1,
                latencyP50Ms: null,
                latencyP95Ms: null,
            },
        ])
    })

    it.each([
        ['an unfinished run', UNFINISHED_RUN_ID],
        ['a path outside the state directory', '..%2F..%2Fetc'],
    ])('answers 404 for %s', async (_, runId) => {
        const { status } = await get(`/api/runs/${runId}`)

        expect(status).toBe(404)
    })

    it('describes each card by what it injects, its load and what judges it, and a card that fails to load by its problems', async () => {
        const { body } = await get('/api/cards')

        expect(body).toEqual([
            {
                ok: false,
                id: 'broken',
                file: path.join(cardsDir, 'broken.yaml'),
                problems: expect.arrayContaining(['version: Invalid input: expected number, received string']),
            },
            expect.objectContaining({ ok: true, id: 'failover', bars: [], runHostOnly: true }),
            expect.objectContaining({
                ok: true,
                id: 'frozen-worker',
                profileName: 'synthetic',
                driveMs: 40_000,
                traffic: [{ name: 'event_webhook', ratePerSecond: 2 }],
                valves: [
                    {
                        valve: 'role.freeze',
                        target: 'cdp-cyclotron-worker-hogflow',
                        dose: {},
                        atMs: null,
                        when: { queue: 'hogflow', atLeast: 2 },
                        forMs: 20_000,
                    },
                ],
                invariants: [
                    { name: 'at_least_once', gate: null },
                    { name: 'duplicate_sends', gate: 0 },
                ],
                bars: [],
                runHostOnly: false,
            }),
            expect.objectContaining({
                ok: true,
                id: 'ramp',
                runHostOnly: true,
                steps: [
                    { scale: 1, fromMs: 0, toMs: 60_000 },
                    { scale: 3, fromMs: 60_000, toMs: 180_000 },
                ],
                bars: [{ name: 'writer_cpu_under', limit: 60, unit: '%' }],
            }),
        ])
    })

    it('follows a run through the live log the runner writes', async () => {
        const truth = [
            { seq: 1, at: iso(-5), kind: 'ses.send', unitId: 'u-0', actionId: 'email', status: 200, detail: {} },
            { seq: 2, at: iso(4), kind: 'ses.send', unitId: 'u-9', actionId: 'email', status: 200, detail: {} },
        ]
        const edge = createServer((request, response) => {
            const url = new URL(request.url ?? '/', 'http://edge')
            const after = Number(url.searchParams.get('after'))
            response.end(
                JSON.stringify(
                    url.pathname === '/_truth/head'
                        ? { head: 1 }
                        : { records: truth.filter(({ seq }) => seq > after), next: 2 }
                )
            )
        })
        await new Promise<void>((resolve) => edge.listen(0, '127.0.0.1', resolve))
        const timeline = [
            { valve: 'role.freeze', target: 'cdp-cyclotron-worker-hogflow', requestedAt: iso(9), appliedAt: iso(10) },
        ]
        const live = openLiveLog(path.join(stateDir, LIVE_RUN_ID))
        live.write({
            type: 'start',
            at: at(-20),
            runId: LIVE_RUN_ID,
            cardId: 'hogflow-worker-frozen',
            cardHash: 'c4rd',
        })
        live.write({ type: 'phase', at: at(0), phase: 'drive', driveForMs: 30_000 })
        live.follow({
            timeline: () => timeline,
            samples: () => [sample(0, 10, 100), sample(5, 12, 150)],
            queue: () => [{ at: at(5), due: 7, running: 2, oldestDueSeconds: 1.5, inserted: 10 }],
            writer: () => [],
            journal: () => [
                {
                    unitId: 'u-9',
                    kind: 'event',
                    teamId: 1,
                    offeredAt: at(1),
                    answer: { accepted: true },
                    expect: { deliveries: ['email'] },
                },
            ],
            edgeUrl: `http://127.0.0.1:${(edge.address() as AddressInfo).port}`,
        })
        await live.stop()
        live.write({ type: 'phase', at: at(30), phase: 'converge' })
        live.write({ type: 'end', at: at(40), status: 'passed', statusReason: 'every invariant held' })
        await new Promise((resolve) => edge.close(resolve))

        const { body } = await get('/api/live')

        expect(body).toMatchObject({
            runId: LIVE_RUN_ID,
            cardId: 'hogflow-worker-frozen',
            cardHash: 'c4rd',
            phase: 'end',
            drive: { startedAt: at(0), endedAt: at(30), forMs: 30_000 },
            ended: { status: 'passed', statusReason: 'every invariant held' },
            state: 'ended',
            hasScorecard: false,
            timeline,
        })
        expect(body.series.roles[0].points).toEqual([expect.objectContaining({ at: at(0), processedPerSecond: 10 })])
        expect(body.series.queue).toEqual([{ at: at(5), due: 7, running: 2, oldestDueSeconds: 1.5 }])
        expect(body.series.flow).toEqual([
            expect.objectContaining({ at: at(0), offeredEvents: 1, emailOk: 1, latencyP50Ms: 3000 }),
        ])
    })

    it('keeps a run live while its runner beats, even through a phase that writes nothing', async () => {
        const ownStateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-viewer-live-'))
        const ownServer = createViewerServer({ stateDir: ownStateDir, cardsDir })
        await new Promise<void>((resolve) => ownServer.listen(0, '127.0.0.1', resolve))
        const own = `http://127.0.0.1:${(ownServer.address() as AddressInfo).port}`
        const runDir = path.join(ownStateDir, LIVE_RUN_ID)
        const minuteAgo = new Date(Date.now() - 60_000)
        const log = openLiveLog(runDir, 10)
        log.write({ type: 'start', at: Date.now(), runId: LIVE_RUN_ID, cardId: 'smoke', cardHash: 'c4rd' })
        log.write({ type: 'phase', at: Date.now(), phase: 'seed' })

        utimesSync(path.join(runDir, LIVE_FILE), minuteAgo, minuteAgo)
        const seeding = await waitForExpect(
            async () => {
                const view = parseJSON(await (await internalFetch(`${own}/api/live`)).text())
                expect(view.state).toBe('running')
                return view
            },
            2000,
            20
        )
        await log.stop()
        await new Promise((resolve) => ownServer.close(resolve))
        rmSync(ownStateDir, { recursive: true, force: true })

        expect(seeding).toMatchObject({ runId: LIVE_RUN_ID, phase: 'seed', state: 'running', ended: null })
    })

    it('reads a run as stopped once its runner stops without an end record', async () => {
        const ownStateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-viewer-stopped-'))
        const runDir = path.join(ownStateDir, UNFINISHED_RUN_ID)
        jest.useFakeTimers()
        try {
            const log = openLiveLog(runDir, 10)
            log.write({ type: 'start', at: Date.now(), runId: UNFINISHED_RUN_ID, cardId: 'smoke', cardHash: 'c4rd' })
            log.write({ type: 'phase', at: Date.now(), phase: 'drive' })
            await log.stop()
            const minuteAgo = new Date(Date.now() - 60_000)
            utimesSync(path.join(runDir, LIVE_FILE), minuteAgo, minuteAgo)
            jest.advanceTimersByTime(1000)

            expect(liveOf(ownStateDir, Date.now())).toMatchObject({
                runId: UNFINISHED_RUN_ID,
                state: 'stopped',
                ended: null,
            })
        } finally {
            jest.useRealTimers()
            rmSync(ownStateDir, { recursive: true, force: true })
        }
    })
})
