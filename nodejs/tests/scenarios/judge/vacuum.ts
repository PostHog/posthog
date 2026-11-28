import { z } from 'zod'

import { VACUUM_PROBE_EVERY_MS } from '../probe/vacuum-cadence'
import type { VacuumRead, VacuumSample } from '../probe/vacuum-probe'
import type { MeasureEvidence, MeasurementDefinition } from './measurements'

type Read = VacuumSample & { at: number }

type Measured = ReturnType<MeasurementDefinition['measure']>[number]

const ENDPOINT_WITHIN_MS = 2 * VACUUM_PROBE_EVERY_MS

const readsOf = (vacuum: readonly VacuumRead[] | undefined): Read[] =>
    (vacuum ?? []).filter((read): read is Read => !('error' in read)).sort((a, b) => a.at - b.at)

const inDrive = (reads: readonly Read[], { drive }: MeasureEvidence): Read[] =>
    reads.filter(({ at }) => at >= drive.startedAt && at <= drive.endedAt)

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
        return [{ value: null, censored: true, unmeasured: endpoints.unmeasured }]
    }
    return measure(endpoints.reads).map((value) => ({
        ...value,
        ...(endpoints.incomplete && { incomplete: true as const }),
    }))
}

export const SOAK_MEASUREMENTS: MeasurementDefinition[] = [
    {
        name: 'cyclotron_jobs_tuples',
        unit: 'tuples',
        params: z.object({}).strict(),
        measure: (evidence) =>
            atEndpoints(evidence, (reads) => {
                const [first, last] = [reads[0], reads.at(-1)!]
                return [
                    { key: 'live_start', value: first.liveTuples },
                    { key: 'live_end', value: last.liveTuples },
                    { key: 'dead_start', value: first.deadTuples },
                    { key: 'dead_end', value: last.deadTuples },
                    { key: 'dead_max', value: Math.max(...reads.map(({ deadTuples }) => deadTuples)) },
                ]
            }),
    },
]
