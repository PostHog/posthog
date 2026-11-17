import { mkdtempSync, readFileSync, rmSync, statSync, utimesSync } from 'fs'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import type { JournalEntry } from '../judge/judge'
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
            edgeUrl: UNREACHABLE_EDGE,
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

    it.each<[string, (log: LiveLog) => Promise<void> | void, boolean]>([
        ['keeps beating while the run is judged after its follow stopped', (log) => log.stop(), true],
        ['stops beating at the end record', (log) => log.write(END), false],
        ['stops beating when the run leaves it without an end record', (log) => log[Symbol.dispose](), false],
    ])('%s', async (_story, leave, beating) => {
        jest.useFakeTimers()
        const log = openLiveLog(runDir, 10)
        log.write(START)

        await leave(log)

        expect(stillBeating()).toBe(beating)
    })
})
