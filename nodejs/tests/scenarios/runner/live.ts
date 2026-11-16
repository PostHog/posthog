import { appendFileSync, mkdirSync } from 'fs'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { JournalEntry } from '../judge/judge'
import type { MetricSample, QueueSample } from '../judge/measurements'
import type { WriterSample } from '../probe/writer-probe'
import type { TruthPage, TruthRecord } from '../provider-edge'
import type { ValveTimelineEntry } from '../valves/valves'

export const LIVE_FILE = 'live.jsonl'

const TICK_MS = 1000
const TRUTH_TIMEOUT_MS = 500

export type LivePhase = 'reset' | 'seed' | 'drive' | 'converge' | 'judge' | 'end'

export type LiveTruth = Pick<TruthRecord, 'seq' | 'at' | 'kind' | 'unitId' | 'actionId' | 'status' | 'fault'>

export type LiveRecord =
    | { type: 'start'; at: number; runId: string; cardId: string }
    | { type: 'phase'; at: number; phase: LivePhase; driveForMs?: number }
    | {
          type: 'tick'
          at: number
          timeline: ValveTimelineEntry[]
          samples: MetricSample[]
          queue: QueueSample[]
          writer: WriterSample[]
          journal: Pick<JournalEntry, 'unitId' | 'kind' | 'offeredAt' | 'answer'>[]
          truth: LiveTruth[]
      }
    | { type: 'end'; at: number; status: string; statusReason: string }

export type LiveSources = {
    timeline(): ValveTimelineEntry[]
    samples(): readonly MetricSample[]
    queue(): readonly QueueSample[]
    writer(): readonly WriterSample[]
    journal(): readonly JournalEntry[]
    edgeUrl: string
}

export interface LiveLog {
    write(record: LiveRecord): void
    follow(sources: LiveSources): void
    stop(): Promise<void>
}

async function truthAfter(edgeUrl: string, after: number): Promise<LiveTruth[]> {
    const response = await internalFetch(`${edgeUrl}/_truth?after=${after}&limit=1000`, {
        timeoutMs: TRUTH_TIMEOUT_MS,
    })
    const page = parseJSON(await response.text()) as TruthPage
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

async function truthHead(edgeUrl: string): Promise<number> {
    const response = await internalFetch(`${edgeUrl}/_truth/head`, { timeoutMs: TRUTH_TIMEOUT_MS })
    return (parseJSON(await response.text()) as { head: number }).head
}

// The live log lets the viewer follow a run while it happens. It only reads what the runner
// already collects, and a write or read that fails turns the log off rather than touching the run.
export function openLiveLog(evidenceDir: string): LiveLog {
    const file = path.join(evidenceDir, LIVE_FILE)
    let broken = false
    const write = (record: LiveRecord): void => {
        if (broken) {
            return
        }
        try {
            mkdirSync(evidenceDir, { recursive: true })
            appendFileSync(file, `${JSON.stringify(record)}\n`)
        } catch {
            broken = true
        }
    }
    const stopped = new AbortController()
    let following: Promise<void> = Promise.resolve()
    return {
        write,
        follow(sources) {
            following = (async () => {
                const seen = { samples: 0, queue: 0, writer: 0, journal: 0, truth: 0 }
                seen.truth = await truthHead(sources.edgeUrl).catch(() => 0)
                // The tick after a stop still runs, so the log ends with what arrived before the judge.
                for (let last = false; !last && !broken; ) {
                    await sleep(TICK_MS, undefined, { signal: stopped.signal }).catch(() => undefined)
                    last = stopped.signal.aborted
                    const fresh = <T>(all: readonly T[], key: keyof typeof seen): T[] => {
                        const taken = all.slice(seen[key])
                        seen[key] = all.length
                        return taken
                    }
                    const truth = await truthAfter(sources.edgeUrl, seen.truth).catch(() => [])
                    seen.truth = truth.at(-1)?.seq ?? seen.truth
                    write({
                        type: 'tick',
                        at: Date.now(),
                        timeline: sources.timeline(),
                        samples: fresh(sources.samples(), 'samples'),
                        queue: fresh(sources.queue(), 'queue'),
                        writer: fresh(sources.writer(), 'writer'),
                        journal: fresh(sources.journal(), 'journal').map(({ unitId, kind, offeredAt, answer }) => ({
                            unitId,
                            kind,
                            offeredAt,
                            answer,
                        })),
                        truth,
                    })
                }
            })()
        },
        async stop() {
            stopped.abort()
            await following
        },
    }
}
