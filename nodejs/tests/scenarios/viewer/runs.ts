import { existsSync, readFileSync, readdirSync, statSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import type { DriveWindow, Measurement } from '../judge/measurements'
import type { RunVerdict } from '../runner/runner'
import type { ScorecardProperties } from '../scorecard/scorecard'
import { Evidence, Series, seriesOf } from './series'

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export type Scorecard = RunVerdict & { event?: ScorecardProperties }

export type RunSummary = Pick<
    RunVerdict,
    'runId' | 'cardId' | 'status' | 'statusReason' | 'startedAt' | 'endedAt' | 'units' | 'invariants' | 'bars'
> & {
    durationS: number
    converged: boolean | null
    unfinishedJobs: number | null
    measurements: Measurement[]
    valves: { valve: string; target: string }[]
    headSha: string | null
    headDirty: boolean | null
    profileName: string | null
    where: 'local' | 'cloud'
}

export type RunDetail = RunSummary & {
    scorecard: Scorecard
    drive: DriveWindow | null
    series: Series
}

export const isRunId = (value: string): boolean => RUN_ID.test(value)

function readJson<T>(file: string): T | undefined {
    if (!existsSync(file)) {
        return undefined
    }
    try {
        return parseJSON(readFileSync(file, 'utf8')) as T
    } catch {
        return undefined
    }
}

function summaryOf(scorecard: Scorecard): RunSummary {
    const event = scorecard.event
    return {
        runId: scorecard.runId,
        cardId: scorecard.cardId,
        status: scorecard.status,
        statusReason: scorecard.statusReason,
        startedAt: scorecard.startedAt,
        endedAt: scorecard.endedAt,
        durationS: (Date.parse(scorecard.endedAt) - Date.parse(scorecard.startedAt)) / 1000,
        units: scorecard.units,
        converged: scorecard.convergence?.converged ?? null,
        unfinishedJobs: scorecard.convergence?.unfinishedJobs ?? null,
        invariants: scorecard.invariants ?? [],
        measurements: scorecard.measurements ?? [],
        bars: scorecard.bars ?? [],
        valves: (scorecard.timeline ?? []).map(({ valve, target }) => ({ valve, target })),
        headSha: typeof event?.head_sha === 'string' ? event.head_sha : null,
        headDirty: typeof event?.head_dirty === 'boolean' ? event.head_dirty : null,
        profileName: typeof event?.profile_name === 'string' ? event.profile_name : null,
        where: String(scorecard.origin ?? event?.origin ?? '').startsWith('cloud') ? 'cloud' : 'local',
    }
}

// A run directory holds a scorecard only once its run ended, so a directory without one is a run
// in progress or a run that crashed, and the list leaves it out.
export function listRuns(stateDir: string): RunSummary[] {
    if (!existsSync(stateDir)) {
        return []
    }
    return readdirSync(stateDir)
        .filter((name) => isRunId(name) && statSync(path.join(stateDir, name)).isDirectory())
        .flatMap((runId) => {
            const scorecard = readJson<Scorecard>(path.join(stateDir, runId, 'scorecard.json'))
            return scorecard?.runId === runId ? [summaryOf(scorecard)] : []
        })
        .sort((a, b) => b.startedAt.localeCompare(a.startedAt))
}

export function runDetailOf(stateDir: string, runId: string): RunDetail | undefined {
    if (!isRunId(runId)) {
        return undefined
    }
    const dir = path.join(stateDir, runId)
    const scorecard = readJson<Scorecard>(path.join(dir, 'scorecard.json'))
    if (scorecard?.runId !== runId) {
        return undefined
    }
    const metrics = readJson<{ samples?: Evidence['samples'] }>(path.join(dir, 'metrics.json'))
    const probes = readJson<{ drive?: DriveWindow | null; writer?: Evidence['writer']; queue?: Evidence['queue'] }>(
        path.join(dir, 'probes.json')
    )
    const evidence: Evidence = {
        samples: metrics?.samples ?? [],
        queue: probes?.queue ?? [],
        writer: probes?.writer ?? [],
        journal: readJson<Evidence['journal']>(path.join(dir, 'journal.json')) ?? [],
        truth: readJson<Evidence['truth']>(path.join(dir, 'truth.json')) ?? [],
    }
    return { ...summaryOf(scorecard), scorecard, drive: probes?.drive ?? null, series: seriesOf(evidence) }
}
