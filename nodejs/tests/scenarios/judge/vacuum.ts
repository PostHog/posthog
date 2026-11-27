import { z } from 'zod'

import { Duration, durationMs } from '../duration'
import { VACUUM_PROBE_EVERY_MS } from '../probe/vacuum-cadence'
import type { SettingType, VacuumRead, VacuumSample } from '../probe/vacuum-probe'
import { WORKER_OF, p99Of, pickupsBetween } from './bars'
import type { MeasureEvidence, MeasurementDefinition } from './measurements'

type Read = VacuumSample & { at: number }

type Window = { from: number; to: number }

type Point = { value: number; censored?: true; incomplete?: true } | { value: null; censored: true; unmeasured: string }

type Measured = ReturnType<MeasurementDefinition['measure']>[number]

const SeriesParams = z
    .object({
        every: Duration.default('10m').refine((every) => durationMs(every) >= VACUUM_PROBE_EVERY_MS, {
            message: `a series window spans at least ${VACUUM_PROBE_EVERY_MS / 1000}s, one vacuum sample`,
        }),
    })
    .strict()

const NO_VACUUM_SAMPLE = 'no vacuum sample in the window'

const MINUTE_MS = 60_000

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

const toastPerRow = (read: Read): number | undefined => perRow(read.toastBytes, read)

const indexesPerRow = (read: Read): number | undefined =>
    perRow(
        Object.values(read.indexBytes).reduce((sum, bytes) => sum + bytes, 0),
        read
    )

const lastOf = (reads: readonly Read[], value: (read: Read) => number | undefined): number | undefined =>
    reads.map(value).findLast((candidate) => candidate !== undefined)

function sinceAutovacuum(read: Read, { drive }: MeasureEvidence): { value: number; censored?: true } {
    return read.lastAutovacuumAt === null
        ? { value: (read.at - drive.startedAt) / 1000, censored: true }
        : { value: (read.at - read.lastAutovacuumAt) / 1000 }
}

type Run = { endedAt: number; seconds?: number }

type Runs = { runs: Run[]; incomplete: boolean }

function drivenRunsOf(evidence: MeasureEvidence): Runs | undefined {
    const { startedAt, endedAt } = evidence.drive
    const reads = readsOf(evidence.vacuum)
    if (reads.length === 0) {
        return undefined
    }
    const opening = reads.findLast(({ at }) => at <= startedAt)
    const closing = reads.find(({ at }) => at >= endedAt)
    const bracketed = reads.filter(({ at }) => at >= (opening?.at ?? -Infinity) && at <= (closing?.at ?? Infinity))
    const runs: Run[] = []
    let incomplete = opening === undefined || closing === undefined
    for (let i = 1; i < bracketed.length; i++) {
        const [previous, current] = [bracketed[i - 1], bracketed[i]]
        const ended = current.autovacuums - previous.autovacuums
        const lastEnd = current.lastAutovacuumAt
        if (ended <= 0 || lastEnd === null) {
            continue
        }
        if (lastEnd >= startedAt && lastEnd <= endedAt) {
            const since = previous.vacuumingSince
            runs.push(
                ended === 1 && since !== null && since > (previous.lastAutovacuumAt ?? -Infinity) && since <= lastEnd
                    ? { endedAt: lastEnd, seconds: (lastEnd - since) / 1000 }
                    : { endedAt: lastEnd }
            )
        }
        const earlier = ended - 1
        if (earlier === 0 || lastEnd < startedAt || previous.at >= endedAt) {
            continue
        }
        if (previous.at >= startedAt && lastEnd <= endedAt) {
            runs.push(...Array.from({ length: earlier }, () => ({ endedAt: lastEnd })))
        } else {
            incomplete = true
        }
    }
    return { runs, incomplete }
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

const UNIT_SCALE: Record<string, number> = {
    B: 1,
    kB: 1024,
    MB: 1024 ** 2,
    GB: 1024 ** 3,
    TB: 1024 ** 4,
    us: 0.001,
    ms: 1,
    s: 1000,
    min: 60_000,
    h: 3_600_000,
    d: 86_400_000,
}

// PostgreSQL takes one value in many spellings: 60s and 1min, 5 in a setting whose unit is s, true and on.
function settingValueOf(value: string, { unit, vartype }: SettingType): string {
    const text = value.trim()
    if (vartype === 'bool') {
        const lower = text.toLowerCase()
        return ['on', 'true', 'yes', '1'].includes(lower)
            ? 'on'
            : ['off', 'false', 'no', '0'].includes(lower)
              ? 'off'
              : text
    }
    const [, number, suffix] = /^(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)$/.exec(text) ?? []
    if (number === undefined || (vartype !== 'integer' && vartype !== 'real')) {
        return text
    }
    const scale = suffix ? UNIT_SCALE[suffix] : unit ? UNIT_SCALE[unit] : 1
    return scale === undefined ? text : String(Number(number) * scale)
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
    soakMeasure('index_bytes_per_row', 'bytes', (evidence) =>
        atEndpoints(evidence, (reads) => {
            const [start, end] = [indexesPerRow(reads[0]), indexesPerRow(reads.at(-1)!)]
            return start === undefined || end === undefined
                ? []
                : [
                      { key: 'start', value: start },
                      { key: 'end', value: end },
                  ]
        })
    ),
    soakMeasure('bloat_growth', 'ratio', (evidence) =>
        atEndpoints(evidence, (reads) => {
            const indexes = [...new Set(reads.flatMap(({ indexBytes }) => Object.keys(indexBytes)))].sort()
            const indexPerRow = (index: string) => (read: Read) =>
                index in read.indexBytes ? perRow(read.indexBytes[index], read) : undefined
            const keyed = (key: string, measured: Measured[]): Measured[] =>
                measured.map((value) => ({ key, ...value }))
            return [
                ...keyed('heap', growthOf(heapPerRow(reads[0]), heapPerRow(reads.at(-1)!))),
                ...keyed('toast', growthOf(toastPerRow(reads[0]), toastPerRow(reads.at(-1)!))),
                ...keyed('indexes', growthOf(indexesPerRow(reads[0]), indexesPerRow(reads.at(-1)!))),
                ...indexes.flatMap((index) =>
                    keyed(`index_${index}`, growthOf(indexPerRow(index)(reads[0]), indexPerRow(index)(reads.at(-1)!)))
                ),
            ]
        })
    ),
    soakMeasure('autovacuum_runs', 'runs', (evidence) => {
        const driven = drivenRunsOf(evidence)
        if (driven === undefined) {
            return []
        }
        const incomplete = driven.incomplete ? { incomplete: true as const } : {}
        return [
            { key: 'count', value: driven.runs.length, ...incomplete },
            { key: 'timed', value: driven.runs.filter(({ seconds }) => seconds !== undefined).length },
        ]
    }),
    soakMeasure('autovacuum_seconds', 's', (evidence) => {
        const timed = (drivenRunsOf(evidence)?.runs ?? [])
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
                          const pickups = pickupsBetween(evidence.samples, [role], window, { straddle: false })
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
    soakMeasure('autovacuum_settings_differ', 'settings', ({ vacuumSettings, autovacuumProfile }) => {
        if (autovacuumProfile === undefined) {
            return [unmeasured('the profile names no autovacuum settings')]
        }
        if (vacuumSettings === undefined || 'error' in vacuumSettings) {
            return [
                unmeasured(`the autovacuum settings were not read${vacuumSettings ? `: ${vacuumSettings.error}` : ''}`),
            ]
        }
        const { settings, types } = vacuumSettings
        const named = Object.keys(autovacuumProfile).sort()
        const unread = named.filter((name) => !(name in settings))
        const differ = named.filter(
            (name) =>
                name in settings &&
                settingValueOf(settings[name], types[name]) !== settingValueOf(autovacuumProfile[name], types[name])
        )
        return [
            { key: 'count', value: differ.length, ...(unread.length > 0 && { incomplete: true as const }) },
            ...differ.map((key) => ({ key, value: 1 })),
            ...unread.map((key) => ({ key, ...unmeasured(`PostgreSQL has no setting ${key}`) })),
        ]
    }),
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
        const read = new Map(
            writerCpu.filter(({ percent }) => Number.isFinite(percent)).map(({ at, percent }) => [at, percent])
        )
        return series(evidence, params, ({ from, to }) => {
            const minutes: number[] = []
            for (let minute = Math.floor(from / MINUTE_MS) * MINUTE_MS; minute < to; minute += MINUTE_MS) {
                minutes.push(minute)
            }
            const peaks = minutes.flatMap((minute) => (read.has(minute) ? [read.get(minute)!] : []))
            if (peaks.length === 0) {
                return unmeasured('no writer CPU minute in the window')
            }
            const missing = minutes.some((minute) => minute + MINUTE_MS <= evidence.drive.endedAt && !read.has(minute))
            return { value: Math.max(...peaks), ...(missing && { incomplete: true as const }) }
        })
    }),
]
