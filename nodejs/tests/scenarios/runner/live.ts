import { appendFileSync, mkdirSync, utimesSync } from 'fs'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import type { JournalEntry } from '../judge/judge'
import type { MetricSample, QueueSample } from '../judge/measurements'
import type { TruthSource } from '../judge/truth'
import type { WriterSample } from '../probe/writer-probe'
import type { TruthRecord } from '../provider-edge'
import type { ValveTimelineEntry } from '../valves/valves'

export const LIVE_FILE = 'live.jsonl'

const TICK_MS = 1000
const TRUTH_TIMEOUT_MS = 500
const TRUTH_PAGE = 1000

export type LivePhase = 'reset' | 'seed' | 'drive' | 'converge' | 'judge' | 'end'

export type LiveTruth = Pick<TruthRecord, 'seq' | 'at' | 'kind' | 'unitId' | 'actionId' | 'status' | 'fault'>

export type LiveRecord =
    | { type: 'start'; at: number; runId: string; cardId: string; cardHash: string }
    | { type: 'phase'; at: number; phase: LivePhase; driveForMs?: number }
    | {
          type: 'tick'
          at: number
          timeline?: ValveTimelineEntry[]
          samples: MetricSample[]
          queue: QueueSample[]
          writer: WriterSample[]
          journal: Pick<JournalEntry, 'unitId' | 'kind' | 'offeredAt' | 'answer' | 'expect'>[]
          truth: LiveTruth[]
      }
    | { type: 'end'; at: number; status: string; statusReason: string }

export type LiveSources = {
    timeline(): ValveTimelineEntry[]
    samples(): readonly MetricSample[]
    queue(): readonly QueueSample[]
    writer(): readonly WriterSample[]
    journal(): readonly JournalEntry[]
    truth: TruthSource
}

export interface LiveLog extends Disposable {
    write(record: LiveRecord): void
    follow(sources: LiveSources): Promise<void>
    stop(): Promise<void>
}

async function truthPage(source: TruthSource, after: number): Promise<LiveTruth[]> {
    const page = await source.after(after, { limit: TRUTH_PAGE, timeoutMs: TRUTH_TIMEOUT_MS })
    return page.records.map(({ seq, at, kind, unitId, actionId, status, fault }) => ({
        seq,
        at,
        kind,
        unitId,
        actionId,
        status,
        fault,
    }))
}

async function truthAfter(source: TruthSource, after: number): Promise<LiveTruth[]> {
    const all: LiveTruth[] = []
    for (let cursor = after; ; ) {
        const page = await truthPage(source, cursor)
        all.push(...page)
        if (page.length < TRUTH_PAGE) {
            return all
        }
        cursor = page.at(-1)!.seq
    }
}

export function openLiveLog(evidenceDir: string, tickMs = TICK_MS): LiveLog {
    const file = path.join(evidenceDir, LIVE_FILE)
    let broken = false
    const beat = setInterval(() => {
        try {
            const now = new Date()
            utimesSync(file, now, now)
        } catch {}
    }, tickMs)
    beat.unref()
    const stopBeat = (): void => clearInterval(beat)
    const write = (record: LiveRecord): void => {
        if (record.type === 'end') {
            stopBeat()
        }
        if (broken) {
            return
        }
        try {
            mkdirSync(evidenceDir, { recursive: true })
            appendFileSync(file, `${JSON.stringify(record)}\n`)
        } catch {
            broken = true
            stopBeat()
        }
    }
    const stopped = new AbortController()
    let following: Promise<void> = Promise.resolve()
    return {
        write,
        follow(sources) {
            following = (async () => {
                const seen = { samples: 0, queue: 0, writer: 0, journal: 0 }
                let timeline = ''
                let truthFrom = await sources.truth.head({ timeoutMs: TRUTH_TIMEOUT_MS }).catch(() => undefined)
                for (let last = false; !last && !broken; ) {
                    await sleep(tickMs, undefined, { signal: stopped.signal }).catch(() => undefined)
                    last = stopped.signal.aborted
                    const fresh = <T>(all: readonly T[], key: keyof typeof seen): T[] => {
                        const taken = all.slice(seen[key])
                        seen[key] = all.length
                        return taken
                    }
                    truthFrom ??= await sources.truth.head({ timeoutMs: TRUTH_TIMEOUT_MS }).catch(() => undefined)
                    const truth =
                        truthFrom === undefined ? [] : await truthAfter(sources.truth, truthFrom).catch(() => [])
                    truthFrom = truth.at(-1)?.seq ?? truthFrom
                    const valves = sources.timeline()
                    const serialized = JSON.stringify(valves)
                    const changed = serialized !== timeline
                    timeline = serialized
                    write({
                        type: 'tick',
                        at: Date.now(),
                        ...(changed ? { timeline: valves } : {}),
                        samples: fresh(sources.samples(), 'samples'),
                        queue: fresh(sources.queue(), 'queue'),
                        writer: fresh(sources.writer(), 'writer'),
                        journal: fresh(sources.journal(), 'journal').map(
                            ({ unitId, kind, offeredAt, answer, expect }) => ({
                                unitId,
                                kind,
                                offeredAt,
                                answer,
                                expect,
                            })
                        ),
                        truth,
                    })
                }
            })().catch(() => undefined)
            return following
        },
        async stop() {
            stopped.abort()
            await following
        },
        [Symbol.dispose]() {
            stopBeat()
            stopped.abort()
        },
    }
}
