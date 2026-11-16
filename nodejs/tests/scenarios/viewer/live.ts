import { existsSync, readFileSync, readdirSync, statSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { LIVE_FILE, LivePhase, LiveRecord } from '../runner/live'
import type { ValveTimelineEntry } from '../valves/valves'
import { isRunId } from './runs'
import { Evidence, Series, seriesOf } from './series'

const STALE_AFTER_MS = 15_000

export type LiveView = {
    runId: string
    cardId: string
    cardHash: string
    startedAt: string
    phase: LivePhase
    phases: { phase: LivePhase; at: number }[]
    drive: { startedAt: number; endedAt: number | null; forMs: number } | null
    ended: { status: string; statusReason: string } | null
    state: 'running' | 'ended' | 'stopped'
    updatedAt: number
    hasScorecard: boolean
    now: number
    timeline: ValveTimelineEntry[]
    series: Series
}

function recordsOf(file: string): LiveRecord[] {
    return readFileSync(file, 'utf8')
        .split('\n')
        .flatMap((line) => {
            if (!line.trim()) {
                return []
            }
            try {
                return [parseJSON(line) as LiveRecord]
            } catch {
                return []
            }
        })
}

function newestLiveDir(stateDir: string): { dir: string; mtimeMs: number } | undefined {
    if (!existsSync(stateDir)) {
        return undefined
    }
    let newest: { dir: string; mtimeMs: number } | undefined
    for (const name of readdirSync(stateDir)) {
        const file = path.join(stateDir, name, LIVE_FILE)
        if (!isRunId(name) || !existsSync(file)) {
            continue
        }
        const { mtimeMs } = statSync(file)
        if (!newest || mtimeMs > newest.mtimeMs) {
            newest = { dir: path.join(stateDir, name), mtimeMs }
        }
    }
    return newest
}

export function liveOf(stateDir: string, now = Date.now()): LiveView | undefined {
    const newest = newestLiveDir(stateDir)
    if (!newest) {
        return undefined
    }
    const { dir, mtimeMs } = newest
    const records = recordsOf(path.join(dir, LIVE_FILE))
    const start = records.find((record) => record.type === 'start')
    if (!start) {
        return undefined
    }
    const evidence = {
        samples: [] as Evidence['samples'][number][],
        queue: [] as Evidence['queue'][number][],
        writer: [] as Evidence['writer'][number][],
        journal: [] as Evidence['journal'][number][],
        truth: [] as Evidence['truth'][number][],
    }
    const phases: LiveView['phases'] = []
    let drive: LiveView['drive'] = null
    let ended: LiveView['ended'] = null
    let timeline: ValveTimelineEntry[] = []
    for (const record of records) {
        switch (record.type) {
            case 'phase':
                phases.push({ phase: record.phase, at: record.at })
                if (record.phase === 'drive') {
                    drive = { startedAt: record.at, endedAt: null, forMs: record.driveForMs ?? 0 }
                } else if (drive && drive.endedAt === null) {
                    drive.endedAt = record.at
                }
                break
            case 'tick':
                timeline = record.timeline ?? timeline
                evidence.samples.push(...record.samples)
                evidence.queue.push(...record.queue)
                evidence.writer.push(...record.writer)
                evidence.journal.push(...record.journal)
                evidence.truth.push(...record.truth)
                break
            case 'end':
                ended = { status: record.status, statusReason: record.statusReason }
                break
        }
    }
    return {
        runId: start.runId,
        cardId: start.cardId,
        cardHash: start.cardHash,
        startedAt: new Date(start.at).toISOString(),
        phase: ended ? 'end' : (phases.at(-1)?.phase ?? 'reset'),
        phases,
        drive,
        ended,
        state: ended ? 'ended' : now - mtimeMs < STALE_AFTER_MS ? 'running' : 'stopped',
        updatedAt: mtimeMs,
        hasScorecard: existsSync(path.join(dir, 'scorecard.json')),
        now,
        timeline,
        series: seriesOf(evidence),
    }
}
