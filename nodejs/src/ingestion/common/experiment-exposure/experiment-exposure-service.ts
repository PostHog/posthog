import { parse as parseUuid, v5 as uuidv5 } from 'uuid'

import { parseTeamsList } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { IngestionConsumerConfig } from '~/ingestion/config'
import { ProcessedEvent } from '~/types'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'
export const EXPERIMENT_EXPOSURE_EVENT = '$experiment_exposure'

export const FEATURE_PROPERTY_PREFIX = '$feature/'

/**
 * Replacement carrier for the per-flag `$feature/<key>` properties, holding
 * flag key to variant for the flags that can back an experiment.
 *
 * Experiments with custom exposure criteria read the variant from
 * `$feature/<flag_key>` on the customer's own event rather than from
 * `$feature_flag_called`, so the per-event flag values cannot simply be dropped:
 * something on every event has to carry the same mapping. This property is that
 * carrier, which is what makes eventually stripping `$feature/*` possible
 * without breaking custom exposure.
 */
export const EXPERIMENT_EXPOSURES_PROPERTY = '$experiment_exposures'

/**
 * Namespace for deriving an exposure event's uuid from its source event's uuid.
 * Randomly generated UUIDv4, fixed forever: changing it would make replayed
 * batches mint fresh uuids and duplicate exposures already in ClickHouse.
 */
const EXPOSURE_UUIDV5_NAMESPACE = parseUuid('6b1f0f3e-2d54-4a7f-9c2b-51d0f2c8a9e4')

const EXPERIMENT_EXPOSURE_MODES = ['disabled', 'metrics', 'enabled'] as const

/**
 * `metrics` classifies and counts without changing the event stream, so it can
 * run fleet-wide to size the migration. `enabled` additionally emits the
 * duplicate $experiment_exposure event, and is gated to an explicit team
 * allowlist.
 */
export type ExperimentExposureMode = (typeof EXPERIMENT_EXPOSURE_MODES)[number]

function isExperimentExposureMode(mode: string): mode is ExperimentExposureMode {
    return (EXPERIMENT_EXPOSURE_MODES as readonly string[]).includes(mode)
}

export interface ExperimentExposureConfig {
    mode: ExperimentExposureMode
    /** '*' for all teams, or an explicit allowlist of team IDs. Only gates `enabled`. */
    teams: number[] | '*'
    /** Escape hatch: teams that never get a duplicate, even when `teams` is '*'. */
    excludedTeams: number[]
}

export function parseExperimentExposureConfig(
    mode: string,
    teams: string,
    excludedTeams: string
): ExperimentExposureConfig {
    let parsedMode: ExperimentExposureMode = 'disabled'
    if (isExperimentExposureMode(mode)) {
        parsedMode = mode
    } else {
        logger.warn('Invalid INGESTION_EXPERIMENT_EXPOSURE_MODE, falling back to disabled', { mode })
    }
    const excluded = parseTeamsList(excludedTeams)
    if (excluded === '*') {
        // '*' as an exclude-everyone switch means "stop writing duplicates". Fall
        // back to metrics rather than disabled so the accounting keeps running,
        // since counting is what the escape hatch is not trying to turn off.
        logger.warn('INGESTION_EXPERIMENT_EXPOSURE_EXCLUDED_TEAMS is "*", downgrading to metrics-only')
        if (parsedMode === 'enabled') {
            parsedMode = 'metrics'
        }
    }
    return {
        mode: parsedMode,
        teams: parseTeamsList(teams),
        excludedTeams: excluded === '*' ? [] : excluded,
    }
}

/** Why an event was treated as an experiment exposure. */
export type ExperimentExposureSignal = 'has_experiment_property' | 'multivariate_response'

export type ExperimentExposureClassification =
    | { kind: 'experiment'; signal: ExperimentExposureSignal; flagKey: string; variant: string }
    | { kind: 'not_experiment' }
    | { kind: 'unclassifiable' }

/**
 * A response of `true`/`false` (or their string spellings, which some SDKs send)
 * means a boolean flag, which under today's flag model cannot carry an
 * experiment. Anything else that is a non-empty string is a variant key.
 */
function variantFromResponse(response: unknown): string | null {
    if (typeof response === 'boolean') {
        return null
    }
    if (typeof response !== 'string' || response === '') {
        return null
    }
    return response === 'true' || response === 'false' ? null : response
}

/**
 * Decides whether one $feature_flag_called event represents an experiment
 * exposure, using only the event payload so that ingestion needs no flag or
 * experiment lookup.
 *
 * Two signals, in order of trustworthiness:
 *
 * 1. `$feature_flag_has_experiment`, which the /flags response populates from
 *    the flag's linked-experiment check. Authoritative, but only newer SDKs
 *    send it, so it cannot be relied on alone yet.
 * 2. A non-boolean `$feature_flag_response`, meaning a multivariate flag. This
 *    is the heuristic the exposure RFC proposes as "good enough for now". It
 *    over-counts, because a multivariate flag need not back an experiment, and
 *    a targeted-release rule that returns a variant value looks identical to a
 *    real exposure.
 *
 * Both signals are payload-shape proxies for "an experiment rule produced this
 * value", which is the thing we actually want and which no current SDK reports.
 * Once the /flags response carries the rule type that produced the value, this
 * function should read that instead of inferring from the value's type, because
 * the flag model is moving toward experiments on boolean flags, at which point
 * response type stops correlating with experiment membership at all.
 */
export function classifyFlagCalledEvent(properties: Record<string, unknown>): ExperimentExposureClassification {
    const flagKey = properties['$feature_flag']
    if (typeof flagKey !== 'string' || flagKey === '') {
        return { kind: 'unclassifiable' }
    }

    const variant = variantFromResponse(properties['$feature_flag_response'])

    if (properties['$feature_flag_has_experiment'] === true) {
        // The flag is known to back an experiment, so this is an exposure even
        // when the response is boolean, which is what an experiment on a
        // boolean flag looks like.
        return {
            kind: 'experiment',
            signal: 'has_experiment_property',
            flagKey,
            variant: variant ?? String(properties['$feature_flag_response'] ?? ''),
        }
    }

    if (variant !== null) {
        return { kind: 'experiment', signal: 'multivariate_response', flagKey, variant }
    }

    return { kind: 'not_experiment' }
}

/**
 * Collects the `$feature/<key>` properties that could back an experiment into a
 * single flag-key-to-variant map, or returns null when the event has none.
 *
 * Only non-boolean values are kept. A boolean `$feature/<key>` comes from a
 * boolean flag, which under today's flag model cannot host an experiment, so it
 * can never be the variant a custom-exposure query reads. Boolean entries are
 * the bulk of these properties by volume, and excluding them is what makes the
 * map materially smaller than the properties it replaces.
 *
 * This becomes wrong once experiments can run on boolean flags, which the flag
 * and experiment integration RFC proposes. At that point the map has to be
 * driven by the rule type reported by /flags rather than by the value's type.
 */
export function buildExperimentExposuresProperty(properties: Record<string, unknown>): Record<string, string> | null {
    let exposures: Record<string, string> | null = null
    for (const [key, value] of Object.entries(properties)) {
        if (!key.startsWith(FEATURE_PROPERTY_PREFIX)) {
            continue
        }
        const variant = variantFromResponse(value)
        if (variant === null) {
            continue
        }
        exposures ??= {}
        exposures[key.slice(FEATURE_PROPERTY_PREFIX.length)] = variant
    }
    return exposures
}

/**
 * Serialized size of a property value or property bag. Used only to compare the
 * parts of an event against each other, so the constant row overhead they all
 * share is deliberately excluded.
 */
export function serializedBytes(value: unknown): number {
    try {
        return JSON.stringify(value)?.length ?? 0
    } catch {
        // Circular or otherwise unserializable properties would already have
        // failed the Kafka produce downstream. Contributing 0 keeps the counter
        // honest instead of aborting classification.
        return 0
    }
}

/**
 * Builds the duplicate $experiment_exposure event.
 *
 * Properties are carried over wholesale, which the RFC leaves as an open
 * question but assumes is acceptable because the exposure volume is a fraction
 * of all flag calls. `$experiment_variant` is added as the resolved variant so
 * experiment queries can read one property regardless of which signal
 * classified the event, and regardless of whether the source flag was boolean
 * or multivariate.
 */
export function buildExposureEvent(
    source: ProcessedEvent,
    classification: Extract<ExperimentExposureClassification, { kind: 'experiment' }>
): ProcessedEvent {
    return {
        ...source,
        uuid: uuidv5(source.uuid, EXPOSURE_UUIDV5_NAMESPACE),
        event: EXPERIMENT_EXPOSURE_EVENT,
        properties: {
            ...source.properties,
            $experiment_variant: classification.variant,
            $feature_flag: classification.flagKey,
        },
    }
}

export interface ExperimentExposureService {
    mode: ExperimentExposureMode
    /** True when this team should get real duplicate events, not just counters. */
    shouldWriteForTeam(teamId: number): boolean
}

export type ExperimentExposureEnvConfig = Pick<
    IngestionConsumerConfig,
    | 'INGESTION_EXPERIMENT_EXPOSURE_MODE'
    | 'INGESTION_EXPERIMENT_EXPOSURE_TEAMS'
    | 'INGESTION_EXPERIMENT_EXPOSURE_EXCLUDED_TEAMS'
>

class ConfiguredExperimentExposureService implements ExperimentExposureService {
    constructor(private readonly config: ExperimentExposureConfig) {}

    get mode(): ExperimentExposureMode {
        return this.config.mode
    }

    shouldWriteForTeam(teamId: number): boolean {
        if (this.config.mode !== 'enabled') {
            return false
        }
        if (this.config.excludedTeams.includes(teamId)) {
            return false
        }
        return this.config.teams === '*' || this.config.teams.includes(teamId)
    }
}

/**
 * Builds the service from ingestion config, or undefined when disabled. The
 * pipeline step treats an absent service as a passthrough.
 */
export function createExperimentExposureService(
    envConfig: ExperimentExposureEnvConfig
): ExperimentExposureService | undefined {
    const config = parseExperimentExposureConfig(
        envConfig.INGESTION_EXPERIMENT_EXPOSURE_MODE,
        envConfig.INGESTION_EXPERIMENT_EXPOSURE_TEAMS,
        envConfig.INGESTION_EXPERIMENT_EXPOSURE_EXCLUDED_TEAMS
    )
    if (config.mode === 'disabled') {
        return undefined
    }
    return new ConfiguredExperimentExposureService(config)
}
