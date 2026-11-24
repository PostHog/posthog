import { createHash } from 'crypto'

import { type LoadedCard, stepsOf } from '../cards'
import type { RunVerdict } from '../runner/runner'
import type { Provenance } from './provenance'

export const SCHEMA_VERSION = 1
export const ADAPTERS: readonly string[] = ['workflows']

type Property = string | number | boolean | null | readonly string[] | unknown[]

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

function measurementProperties(result: RunVerdict): Record<string, Property> {
    return Object.fromEntries(
        result.measurements.flatMap(({ name, key, value, incomplete, censored }) => {
            const property = ['m', name, key]
                .filter((part) => part !== undefined)
                .join('_')
                .replace(/-/g, '_')
            return [
                [property, value],
                ...(incomplete ? [[`${property}_incomplete`, true]] : []),
                ...(censored ? [[`${property}_censored`, true]] : []),
            ]
        })
    )
}

const stepsOfRamp = (
    steps: NonNullable<RunVerdict['units']>['steps'],
    rates: NonNullable<RunVerdict['ramp']>['rates']
): unknown[] =>
    steps.map(({ index, scale, startedAt, endedAt, waitedFor }) => {
        const rated = rates?.find((step) => step.index === index)
        return {
            scale,
            started_at: new Date(startedAt).toISOString(),
            ended_at: new Date(endedAt).toISOString(),
            stretched:
                waitedFor === undefined
                    ? null
                    : `held the ${scale}x rate past its planned end until the ${steps[waitedFor].scale}x step was judged`,
            expected: rated?.expected ?? null,
            lost: rated?.lost ?? null,
            loss_rate: rated?.lossRate ?? null,
            sent: rated?.sent ?? null,
            duplicates: rated?.duplicates ?? null,
            duplicate_rate: rated?.duplicateRate ?? null,
            refused: rated?.refused ?? null,
            refused_rate: rated?.refusedRate ?? null,
        }
    })

function ranToEnd({ units }: RunVerdict, { card }: Pick<LoadedCard, 'card'>): boolean | null {
    const planned = stepsOf(card.drive)
    const steps = units?.steps ?? []
    const last = steps.at(-1)
    if (last === undefined) {
        return null
    }
    const { fromMs, toMs } = planned[planned.length - 1]
    return steps.length === planned.length && last.endedAt - last.startedAt >= toMs - fromMs
}

function rampProperties(result: RunVerdict, loaded: Pick<LoadedCard, 'card'>): Record<string, Property> {
    const { ramp, units } = result
    const stop = ramp?.stop
    return {
        ramp_steps: ramp && units ? stepsOfRamp(units.steps, ramp.rates) : null,
        ramp_ran_to_end: ramp ? ranToEnd(result, loaded) : null,
        ramp_stop: stop?.failure ?? null,
        ramp_stop_scale: stop?.scale ?? null,
        ramp_stop_reason: stop?.reason ?? null,
        ramp_end: ramp?.end ?? null,
        ramp_sustained_scale: ramp?.sustainedScale ?? null,
        ramp_broke_scale: ramp?.broke?.scale ?? null,
        ramp_broke_offered_per_s: ramp?.broke?.offeredPerSecond ?? null,
        ramp_broke_by: ramp?.broke?.by ?? null,
        ramp_broke_kind: ramp?.broke?.kind ?? null,
        ramp_broke_at: ramp?.broke?.at ?? null,
        ramp_broke_part: ramp?.broke?.part ?? null,
        ramp_end_reason: ramp?.reason ?? null,
    }
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
              .update(
                  JSON.stringify([result.target, provenance.hostCpu, provenance.hostMemoryGb, ...versions, card.seed])
              )
              .digest('hex')
    return {
        schema_version: SCHEMA_VERSION,
        run_id: result.runId,
        adapters: ADAPTERS,
        owners: [],
        card_id: result.cardId,
        card_version: card.version,
        card_hash: result.cardHash,
        profile_name: profile.name,
        profile_hash: result.profileHash,
        topology_hash: result.topologyHash ?? null,
        head_sha: provenance.headSha,
        head_dirty: provenance.headDirty,
        origin: result.origin,
        target: result.target,
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
        send_retries: result.units?.sendRetries ?? null,
        converged: result.convergence?.converged ?? null,
        unfinished_jobs: result.convergence?.unfinishedJobs ?? null,
        janitor_resets: result.janitorResets ?? null,
        ...invariantProperties(result),
        ...measurementProperties(result),
        ...(card.drive.stopOnBreak === true ? rampProperties(result, { card }) : {}),
        admissions: result.admissions,
        bars: result.bars,
        valve_timeline: result.timeline,
        role_restarts: result.restarts ?? [],
        evidence_dir: result.evidenceDir,
    }
}
