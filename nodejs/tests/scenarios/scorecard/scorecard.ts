import { createHash } from 'crypto'

import type { LoadedCard } from '../cards'
import type { RunVerdict } from '../runner/runner'
import type { Provenance } from './provenance'

export const SCHEMA_VERSION = 1
export const TARGET = 'local'

type Property = string | number | boolean | null | string[] | unknown[]

export type ScorecardProperties = { run_id: string; ended_at: string } & Record<string, Property>

function invariantProperties(result: RunVerdict): Record<string, Property> {
    return Object.fromEntries([
        ...result.invariants.flatMap(({ name, passed, observed, gate, violation, unitIds }) => [
            [`inv_${name}_passed`, passed],
            [`inv_${name}_observed`, observed],
            [`inv_${name}_gate`, gate ?? null],
            [`inv_${name}_violation`, violation ?? null],
            [`inv_${name}_ids`, unitIds],
        ]),
        ['invariants_failed', result.invariants.filter(({ passed }) => !passed).map(({ name }) => name)],
    ])
}

export function scorecardOf(
    result: RunVerdict,
    { card, profile }: LoadedCard,
    provenance: Provenance
): ScorecardProperties {
    const versions = [provenance.runnerVersion, provenance.generatorVersion, provenance.valvesVersion]
    const fingerprint = versions.includes(null)
        ? null
        : createHash('sha256')
              .update(JSON.stringify([TARGET, provenance.hostCpu, provenance.hostMemoryGb, ...versions, card.seed]))
              .digest('hex')
    return {
        schema_version: SCHEMA_VERSION,
        run_id: result.runId,
        card_id: result.cardId,
        card_version: card.version,
        card_hash: result.cardHash,
        profile_name: profile.name,
        profile_hash: result.profileHash,
        head_sha: provenance.headSha,
        head_dirty: provenance.headDirty,
        origin: result.origin,
        target: TARGET,
        fingerprint,
        host_cpu: provenance.hostCpu,
        host_memory_gb: provenance.hostMemoryGb,
        runner_version: provenance.runnerVersion,
        generator_version: provenance.generatorVersion,
        valves_version: provenance.valvesVersion,
        seed: card.seed,
        status: result.status,
        status_reason: result.statusReason,
        started_at: result.startedAt,
        ended_at: result.endedAt,
        duration_s: (Date.parse(result.endedAt) - Date.parse(result.startedAt)) / 1000,
        units_target: result.units?.targetUnits ?? null,
        units_offered: result.units?.offeredUnits ?? null,
        converged: result.convergence?.converged ?? null,
        unfinished_jobs: result.convergence?.unfinishedJobs ?? null,
        ...invariantProperties(result),
        valve_timeline: result.timeline,
        evidence_dir: result.evidenceDir,
    }
}
