import { z } from 'zod'

import { Duration, durationMs } from '../duration'
import type { VacuumRead, VacuumSample } from '../probe/vacuum-probe'
import { WORKER_OF, p99Of, pickupsBetween } from './bars'
import type { MeasureEvidence, MeasurementDefinition } from './measurements'

type Read = VacuumSample & { at: number }

type Window = { from: number; to: number }

type Point = { value: number; censored?: true } | { value: null; censored: true; unmeasured: string }

type Measured = ReturnType<MeasurementDefinition['measure']>[number]

const SeriesParams = z.object({ every: Duration.default('10m') }).strict()

const NO_VACUUM_SAMPLE = 'no vacuum sample in the window'

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

function series(evidence: MeasureEvidence, params: unknown, point: (window: Window) => Point, prefix = ''): Measured[] {
    return windowsOf(evidence, params).map((window) => ({
        key: `${prefix}t${(window.from - evidence.drive.startedAt) / 1000}`,
        ...point(window),
    }))
}

const within = (reads: readonly Read[], { from, to }: Window): Read[] => reads.filter(({ at }) => at >= from && at < to)

const maxPoint = (values: number[], reason = NO_VACUUM_SAMPLE): Point =>
    values.length === 0 ? unmeasured(reason) : { value: Math.max(...values) }

const deadShareOf = ({ liveTuples, deadTuples }: Read): number =>
    liveTuples + deadTuples === 0 ? 0 : deadTuples / (liveTuples + deadTuples)

const perRow = (bytes: number, { liveTuples }: Read): number | undefined =>
    liveTuples > 0 ? bytes / liveTuples : undefined

const heapPerRow = (read: Read): number | undefined => perRow(read.heapBytes, read)

const indexesPerRow = (read: Read): number | undefined =>
    perRow(
        Object.values(read.indexBytes).reduce((sum, bytes) => sum + bytes, 0),
        read
    )

const lastOf = (reads: readonly Read[], value: (read: Read) => number | undefined): number | undefined =>
    reads.map(value).findLast((candidate) => candidate !== undefined)

const firstOf = (reads: readonly Read[], value: (read: Read) => number | undefined): number | undefined =>
    reads.map(value).find((candidate) => candidate !== undefined)

function sinceAutovacuum(read: Read, { drive }: MeasureEvidence): { value: number; censored?: true } {
    return read.lastAutovacuumAt === null
        ? { value: (read.at - drive.startedAt) / 1000, censored: true }
        : { value: (read.at - read.lastAutovacuumAt) / 1000 }
}

type Run = { endedAt: number; seconds?: number }

function runsOf(reads: readonly Read[]): Run[] {
    const runs: Run[] = []
    let lastEnd = -Infinity
    for (let i = 1; i < reads.length; i++) {
        const ended = reads[i].autovacuums - reads[i - 1].autovacuums
        const endedAt = reads[i].lastAutovacuumAt
        if (ended <= 0 || endedAt === null) {
            continue
        }
        const startedAt = reads
            .slice(0, i + 1)
            .map(({ vacuumingSince }) => vacuumingSince)
            .findLast((since): since is number => since !== null && since > lastEnd && since <= endedAt)
        runs.push(...Array.from({ length: ended - 1 }, () => ({ endedAt })))
        runs.push(startedAt === undefined ? { endedAt } : { endedAt, seconds: (endedAt - startedAt) / 1000 })
        lastEnd = endedAt
    }
    return runs
}

const nearestRank = (sorted: number[], share: number): number => sorted[Math.ceil(share * sorted.length) - 1]

const growthOf = (start: number | undefined, end: number | undefined): Measured[] =>
    start === undefined || end === undefined || start === 0 ? [] : [{ value: end / start }]

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
    soakMeasure('cyclotron_jobs_tuples', 'tuples', (evidence) => {
        const reads = inDrive(readsOf(evidence.vacuum), evidence)
        if (reads.length === 0) {
            return []
        }
        const [first, last] = [reads[0], reads.at(-1)!]
        return [
            { key: 'live_start', value: first.liveTuples },
            { key: 'live_end', value: last.liveTuples },
            { key: 'dead_start', value: first.deadTuples },
            { key: 'dead_end', value: last.deadTuples },
            { key: 'dead_max', value: Math.max(...reads.map(({ deadTuples }) => deadTuples)) },
        ]
    }),
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
    soakMeasure('index_bytes_per_row', 'bytes', (evidence) => {
        const reads = inDrive(readsOf(evidence.vacuum), evidence)
        const [start, end] = [firstOf(reads, indexesPerRow), lastOf(reads, indexesPerRow)]
        return start === undefined || end === undefined
            ? []
            : [
                  { key: 'start', value: start },
                  { key: 'end', value: end },
              ]
    }),
    soakMeasure('bloat_growth', 'ratio', (evidence) => {
        const reads = inDrive(readsOf(evidence.vacuum), evidence)
        const indexes = [...new Set(reads.flatMap(({ indexBytes }) => Object.keys(indexBytes)))].sort()
        const indexPerRow = (index: string) => (read: Read) =>
            index in read.indexBytes ? perRow(read.indexBytes[index], read) : undefined
        const keyed = (key: string, measured: Measured[]): Measured[] => measured.map((value) => ({ key, ...value }))
        return [
            ...keyed('heap', growthOf(firstOf(reads, heapPerRow), lastOf(reads, heapPerRow))),
            ...keyed('indexes', growthOf(firstOf(reads, indexesPerRow), lastOf(reads, indexesPerRow))),
            ...indexes.flatMap((index) =>
                keyed(`index_${index}`, growthOf(firstOf(reads, indexPerRow(index)), lastOf(reads, indexPerRow(index))))
            ),
        ]
    }),
    soakMeasure('autovacuum_runs', 'runs', (evidence) => {
        const reads = readsOf(evidence.vacuum)
        const opening = reads.findLast(({ at }) => at < evidence.drive.startedAt)
        const runs = runsOf([...(opening ? [opening] : []), ...inDrive(reads, evidence)])
        return reads.length === 0
            ? []
            : [
                  { key: 'count', value: runs.length },
                  { key: 'timed', value: runs.filter(({ seconds }) => seconds !== undefined).length },
              ]
    }),
    soakMeasure('autovacuum_seconds', 's', (evidence) => {
        const reads = readsOf(evidence.vacuum)
        const opening = reads.findLast(({ at }) => at < evidence.drive.startedAt)
        const timed = runsOf([...(opening ? [opening] : []), ...inDrive(reads, evidence)])
            .flatMap(({ seconds }) => (seconds === undefined ? [] : [seconds]))
            .sort((a, b) => a - b)
        return timed.length === 0
            ? []
            : [
                  { key: 'p50', value: nearestRank(timed, 0.5) },
                  { key: 'max', value: timed.at(-1)! },
              ]
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
    seriesMeasure('pickup_p99_seconds', 's', (evidence, params) =>
        Object.entries(WORKER_OF).flatMap(([queue, role]) =>
            evidence.samples.some((sample) => sample.role === role)
                ? series(
                      evidence,
                      params,
                      (window) => {
                          const pickups = pickupsBetween(evidence.samples, [role], window)
                          if ('unread' in pickups) {
                              return unmeasured(pickups.unread)
                          }
                          const buckets = pickups.picked[queue] ?? {}
                          if ((buckets['+Inf'] ?? 0) === 0) {
                              return unmeasured('no pickups in the window')
                          }
                          const { value, beyond } = p99Of(buckets)
                          return beyond ? { value, censored: true } : { value }
                      },
                      `${queue}_`
                  )
                : []
        )
    ),
    seriesMeasure('writer_cpu_percent', '%', (evidence, params) => {
        const { writerCpu } = evidence
        if (writerCpu === undefined || !Array.isArray(writerCpu)) {
            const reason =
                writerCpu === undefined
                    ? 'no writer CPU was read'
                    : 'unread' in writerCpu
                      ? writerCpu.unread
                      : writerCpu.unsourced
            return [{ value: null, censored: true, unmeasured: reason }]
        }
        return series(evidence, params, ({ from, to }) =>
            maxPoint(
                writerCpu
                    .filter(({ at, percent }) => at >= from && at < to && Number.isFinite(percent))
                    .map(({ percent }) => percent),
                'no writer CPU minute in the window'
            )
        )
    }),
]
