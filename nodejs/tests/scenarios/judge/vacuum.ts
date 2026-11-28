import { z } from 'zod'

import { Duration, durationMs } from '../duration'
import { VACUUM_PROBE_EVERY_MS } from '../probe/vacuum-cadence'
import type { VacuumRead, VacuumSample } from '../probe/vacuum-probe'
import type { MeasureEvidence, MeasurementDefinition } from './measurements'

type Read = VacuumSample & { at: number }

type Window = { from: number; to: number }

type Point = { value: number; censored?: true } | { value: null; censored: true; unmeasured: string }

type Measured = ReturnType<MeasurementDefinition['measure']>[number]

const SeriesParams = z
    .object({
        every: Duration.default('10m').refine((every) => durationMs(every) >= VACUUM_PROBE_EVERY_MS, {
            message: `a series window spans at least ${VACUUM_PROBE_EVERY_MS / 1000}s, one vacuum sample`,
        }),
    })
    .strict()

const NO_VACUUM_SAMPLE = 'no vacuum sample in the window'

const ENDPOINT_WITHIN_MS = 2 * VACUUM_PROBE_EVERY_MS

const readsOf = (vacuum: readonly VacuumRead[] | undefined): Read[] =>
    (vacuum ?? []).filter((read): read is Read => !('error' in read)).sort((a, b) => a.at - b.at)

const inDrive = (reads: readonly Read[], { drive }: MeasureEvidence): Read[] =>
    reads.filter(({ at }) => at >= drive.startedAt && at <= drive.endedAt)

function windowsOf({ drive }: MeasureEvidence, params: unknown): Window[] {
    const every = durationMs(SeriesParams.parse(params).every)
    const windows: Window[] = []
    for (let from = drive.startedAt; from < drive.endedAt; from += every) {
        windows.push({ from, to: Math.min(from + every, drive.endedAt) })
    }
    return windows
}

const unmeasured = (reason: string): Point => ({ value: null, censored: true, unmeasured: reason })

function series(evidence: MeasureEvidence, params: unknown, point: (window: Window) => Point): Measured[] {
    return windowsOf(evidence, params).map((window) => ({
        key: `t${(window.from - evidence.drive.startedAt) / 1000}`,
        ...point(window),
    }))
}

const within = (reads: readonly Read[], { from, to }: Window): Read[] => reads.filter(({ at }) => at >= from && at < to)

const maxPoint = (values: number[]): Point =>
    values.length === 0 ? unmeasured(NO_VACUUM_SAMPLE) : { value: Math.max(...values) }

const deadShareOf = ({ liveTuples, deadTuples }: Read): number =>
    liveTuples + deadTuples === 0 ? 0 : deadTuples / (liveTuples + deadTuples)

const perRow = (bytes: number, { liveTuples }: Read): number | undefined =>
    liveTuples > 0 ? bytes / liveTuples : undefined

const heapPerRow = (read: Read): number | undefined => perRow(read.heapBytes, read)

const lastOf = (reads: readonly Read[], value: (read: Read) => number | undefined): number | undefined =>
    reads.map(value).findLast((candidate) => candidate !== undefined)

function sinceAutovacuum(read: Read, { drive }: MeasureEvidence): { value: number; censored?: true } {
    return read.lastAutovacuumAt === null
        ? { value: (read.at - drive.startedAt) / 1000, censored: true }
        : { value: (read.at - read.lastAutovacuumAt) / 1000 }
}

function endpointsOf(evidence: MeasureEvidence): { reads: Read[]; incomplete?: true } | { unmeasured: string } {
    const reads = inDrive(readsOf(evidence.vacuum), evidence)
    if (reads.length < 2) {
        return { unmeasured: 'fewer than two vacuum samples in the drive' }
    }
    const gapped =
        reads[0].at - evidence.drive.startedAt > ENDPOINT_WITHIN_MS ||
        evidence.drive.endedAt - reads.at(-1)!.at > ENDPOINT_WITHIN_MS
    return { reads, ...(gapped && { incomplete: true as const }) }
}

const atEndpoints = (evidence: MeasureEvidence, measure: (reads: Read[]) => Measured[]): Measured[] => {
    const endpoints = endpointsOf(evidence)
    if ('unmeasured' in endpoints) {
        return [unmeasured(endpoints.unmeasured)]
    }
    return measure(endpoints.reads).map((value) => ({
        ...value,
        ...(endpoints.incomplete && { incomplete: true as const }),
    }))
}

const soakMeasure = (
    name: string,
    unit: string,
    measure: (evidence: MeasureEvidence) => Measured[]
): MeasurementDefinition => ({ name, unit, params: z.object({}).strict(), measure })

const seriesMeasure = (
    name: string,
    unit: string,
    measure: (evidence: MeasureEvidence, params: unknown) => Measured[]
): MeasurementDefinition => ({ name, unit, params: SeriesParams, measure })

export const SOAK_MEASUREMENTS: MeasurementDefinition[] = [
    soakMeasure('cyclotron_jobs_tuples', 'tuples', (evidence) =>
        atEndpoints(evidence, (reads) => {
            const [first, last] = [reads[0], reads.at(-1)!]
            return [
                { key: 'live_start', value: first.liveTuples },
                { key: 'live_end', value: last.liveTuples },
                { key: 'dead_start', value: first.deadTuples },
                { key: 'dead_end', value: last.deadTuples },
                { key: 'dead_max', value: Math.max(...reads.map(({ deadTuples }) => deadTuples)) },
            ]
        })
    ),
    seriesMeasure('dead_tuple_share', 'share', (evidence, params) => {
        const reads = readsOf(evidence.vacuum)
        return series(evidence, params, (window) => maxPoint(within(reads, window).map(deadShareOf)))
    }),
    seriesMeasure('heap_bytes_per_row', 'bytes', (evidence, params) => {
        const reads = readsOf(evidence.vacuum)
        return series(evidence, params, (window) => {
            const value = lastOf(within(reads, window), heapPerRow)
            return value === undefined ? unmeasured(NO_VACUUM_SAMPLE) : { value }
        })
    }),
    seriesMeasure('seconds_since_autovacuum', 's', (evidence, params) => {
        const reads = readsOf(evidence.vacuum)
        return series(evidence, params, (window) => {
            const since = within(reads, window).map((read) => sinceAutovacuum(read, evidence))
            return since.length === 0
                ? unmeasured(NO_VACUUM_SAMPLE)
                : {
                      value: Math.max(...since.map(({ value }) => value)),
                      ...(since.some(({ censored }) => censored) ? { censored: true as const } : {}),
                  }
        })
    }),
]
