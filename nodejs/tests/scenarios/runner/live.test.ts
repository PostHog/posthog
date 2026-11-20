import { mkdtempSync, readFileSync, rmSync, statSync, utimesSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import type { JournalEntry } from '../judge/judge'
import type { MetricSample } from '../judge/measurements'
import { edgeTruth } from '../judge/truth'
import type { TruthRecord } from '../provider-edge/truth'
import type { ValveTimelineEntry } from '../valves/valves'
import { LIVE_FILE, LiveLog, LiveRecord, openLiveLog } from './live'

const UNREACHABLE_EDGE = 'http://127.0.0.1:1'
const RUN_ID = '3f2a9c4e-7b1d-4e8a-9c05-2d6b8e1f4a73'
const START: LiveRecord = {
    type: 'start',
    at: 1_767_225_600_000,
    runId: RUN_ID,
    cardId: 'smoke',
    cardHash: 'c4rd',
}
const SEEDING: LiveRecord = { type: 'phase', at: 1_767_225_601_000, phase: 'seed' }
const END: LiveRecord = { type: 'end', at: 1_767_225_690_000, status: 'passed', statusReason: 'every invariant held' }
const VALVE: ValveTimelineEntry = {
    valve: 'kill',
    target: 'cdp-cyclotron-worker-email',
    requestedAt: '2026-01-01T00:00:30.000Z',
    appliedAt: '2026-01-01T00:00:31.000Z',
}
const OFFERED: JournalEntry = {
    unitId: 'run-a-1',
    kind: 'event',
    teamId: 7,
    offeredAt: 1_767_225_620_000,
    answer: { accepted: true },
    expect: { deliveries: ['email'] },
    followUp: { notSent: 'no follow-up for this unit' },
}

describe('live log', () => {
    let scratch: string
    let runDir: string

    const file = (): string => path.join(runDir, LIVE_FILE)
    const linesOf = (): unknown[] =>
        readFileSync(file(), 'utf8')
            .trimEnd()
            .split('\n')
            .map((line) => parseJSON(line))
    const stillBeating = (): boolean => {
        const minuteAgo = new Date(Date.now() - 60_000)
        utimesSync(file(), minuteAgo, minuteAgo)
        jest.advanceTimersByTime(50)
        return statSync(file()).mtimeMs > minuteAgo.getTime()
    }

    beforeEach(() => {
        scratch = mkdtempSync(path.join(os.tmpdir(), 'scenario-live-'))
        runDir = path.join(scratch, RUN_ID)
    })

    afterEach(() => {
        jest.useRealTimers()
        rmSync(scratch, { recursive: true, force: true })
    })

    it('writes the v1 line format: one record per line, ticks carry the timeline and the journal fields a viewer reads', async () => {
        const log = openLiveLog(runDir)
        log.write(START)
        log.write(SEEDING)

        log.follow({
            timeline: () => [VALVE],
            samples: () => [],
            queue: () => [],
            writer: () => [],
            journal: () => [OFFERED],
            truth: edgeTruth(UNREACHABLE_EDGE),
        })
        await log.stop()
        log.write(END)

        expect(linesOf()).toEqual([
            START,
            SEEDING,
            {
                type: 'tick',
                at: expect.any(Number),
                timeline: [VALVE],
                samples: [],
                queue: [],
                writer: [],
                journal: [
                    {
                        unitId: 'run-a-1',
                        kind: 'event',
                        offeredAt: 1_767_225_620_000,
                        answer: { accepted: true },
                        expect: { deliveries: ['email'] },
                    },
                ],
                truth: [],
            },
            END,
        ])
    })

    it('appends only the evidence that arrived since the tick before', async () => {
        const first: MetricSample = {
            role: 'cdp-api',
            replica: 0,
            at: 1_767_225_630_000,
            startedAt: 1_767_225_600_000,
            cpuSeconds: 3,
            rssBytes: 200_000_000,
            processed: { event: 4 },
            pgClientErrors: 0,
            consumerLoopErrors: 0,
            janitorStalled: 0,
            lateness: {},
        }
        const second: MetricSample = { ...first, at: 1_767_225_631_000, cpuSeconds: 4 }
        let reads = 0
        let readTwice: () => void = () => undefined
        const secondRead = new Promise<void>((resolve) => (readTwice = resolve))
        const log = openLiveLog(runDir, 10)
        log.write(START)

        log.follow({
            timeline: () => [],
            samples: () => {
                reads += 1
                if (reads === 2) {
                    readTwice()
                }
                return reads === 1 ? [first] : [first, second]
            },
            queue: () => [],
            writer: () => [],
            journal: () => [],
            truth: edgeTruth(UNREACHABLE_EDGE),
        })
        await secondRead
        await log.stop()

        expect(linesOf().map((line) => (line as { samples?: MetricSample[] }).samples)).toEqual([
            undefined,
            [first],
            [second],
            [],
        ])
    })

    it('stops following when the run leaves it without stopping it', async () => {
        const log = openLiveLog(runDir, 10)
        log.write(START)

        const following = log.follow({
            timeline: () => [],
            samples: () => [],
            queue: () => [],
            writer: () => [],
            journal: () => [],
            truth: edgeTruth(UNREACHABLE_EDGE),
        })
        log[Symbol.dispose]()
        await following

        expect(linesOf()).toEqual([START, expect.objectContaining({ type: 'tick' })])
    })

    it('stops following without failing the run when a source throws', async () => {
        const log = openLiveLog(runDir)
        log.write(START)
        log.follow({
            timeline: () => {
                throw new Error('the valves are gone')
            },
            samples: () => [],
            queue: () => [],
            writer: () => [],
            journal: () => [],
            truth: edgeTruth(UNREACHABLE_EDGE),
        })

        await expect(log.stop()).resolves.toBeUndefined()
        log.write(END)
        expect(linesOf()).toEqual([START, END])
    })

    it("follows only this run's truth when the edge cannot name its head at first", async () => {
        const records: TruthRecord[] = [1, 2, 3].map((seq) => ({
            seq,
            at: new Date(seq).toISOString(),
            kind: 'webhook',
            unitId: `unit-${seq}`,
            actionId: 'webhook',
            status: 200,
            detail: {},
        }))
        let headReads = 0
        let headFailed: () => void = () => undefined
        const firstHeadFailed = new Promise<void>((resolve) => (headFailed = resolve))
        const edge = http.createServer((request, response) => {
            const url = new URL(request.url!, 'http://edge')
            if (url.pathname === '/_truth/head') {
                headReads += 1
                if (headReads === 1) {
                    response.writeHead(500).end()
                    headFailed()
                    return
                }
                response.end(JSON.stringify({ head: 2 }))
                return
            }
            const after = Number(url.searchParams.get('after'))
            const page = records.filter(({ seq }) => seq > after)
            response.end(JSON.stringify({ records: page, next: page.at(-1)?.seq ?? after }))
        })
        await new Promise<void>((resolve) => edge.listen(0, '127.0.0.1', resolve))
        const log = openLiveLog(runDir)
        log.write(START)

        log.follow({
            timeline: () => [],
            samples: () => [],
            queue: () => [],
            writer: () => [],
            journal: () => [],
            truth: edgeTruth(`http://127.0.0.1:${(edge.address() as AddressInfo).port}`),
        })
        await firstHeadFailed
        await log.stop()
        await new Promise((resolve) => edge.close(resolve))

        expect(linesOf()).toEqual([
            START,
            expect.objectContaining({
                type: 'tick',
                truth: [
                    { seq: 3, at: records[2].at, kind: 'webhook', unitId: 'unit-3', actionId: 'webhook', status: 200 },
                ],
            }),
        ])
    })

    it.each<[string, (log: LiveLog) => Promise<void> | void, boolean]>([
        ['keeps beating while the run is judged after its follow stopped', (log) => log.stop(), true],
        ['stops beating at the end record', (log) => log.write(END), false],
        ['stops beating when the run leaves it without an end record', (log) => log[Symbol.dispose](), false],
        [
            'keeps beating past a beat that failed',
            (log) => {
                rmSync(file())
                jest.advanceTimersByTime(50)
                log.write(SEEDING)
            },
            true,
        ],
    ])('%s', async (_story, leave, beating) => {
        jest.useFakeTimers()
        const log = openLiveLog(runDir, 10)
        log.write(START)

        await leave(log)

        expect(stillBeating()).toBe(beating)
    })
})
