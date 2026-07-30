import { parse as parseUuid, v5 as uuidv5 } from 'uuid'

import { parseTeamsList } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { IngestionConsumerConfig } from '~/ingestion/config'
import { ProcessedEvent } from '~/types'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'
export const EXPERIMENT_EXPOSURE_EVENT = '$experiment_exposure'

export const FEATURE_PROPERTY_PREFIX = '$feature/'
export const EXPERIMENT_EXPOSURES_PROPERTY = '$experiment_exposures'

// Must remain stable so replaying a source event produces the same exposure UUID.
const EXPOSURE_UUIDV5_NAMESPACE = parseUuid('6b1f0f3e-2d54-4a7f-9c2b-51d0f2c8a9e4')

const EXPERIMENT_EXPOSURE_MODES = ['disabled', 'metrics', 'enabled'] as const

export type ExperimentExposureMode = (typeof EXPERIMENT_EXPOSURE_MODES)[number]

function isExperimentExposureMode(mode: string): mode is ExperimentExposureMode {
    return (EXPERIMENT_EXPOSURE_MODES as readonly string[]).includes(mode)
}

export interface ExperimentExposureConfig {
    mode: ExperimentExposureMode
    teams: number[] | '*'
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

export type ExperimentExposureSignal = 'has_experiment_property' | 'multivariate_response'

export type ExperimentExposureClassification =
    | { kind: 'experiment'; signal: ExperimentExposureSignal; flagKey: string; variant: string }
    | { kind: 'not_experiment' }
    | { kind: 'unclassifiable' }

function variantFromResponse(response: unknown): string | null {
    if (typeof response !== 'string' || response === '') {
        return null
    }
    return response === 'true' || response === 'false' ? null : response
}

// A multivariate response is a fallback heuristic for SDKs that do not yet send
// $feature_flag_has_experiment. It can include non-experiment multivariate flags.
export function classifyFlagCalledEvent(properties: Record<string, unknown>): ExperimentExposureClassification {
    const flagKey = properties['$feature_flag']
    if (typeof flagKey !== 'string' || flagKey === '') {
        return { kind: 'unclassifiable' }
    }

    const variant = variantFromResponse(properties['$feature_flag_response'])

    if (properties['$feature_flag_has_experiment'] === true) {
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

export function serializedBytes(value: unknown): number {
    try {
        return JSON.stringify(value)?.length ?? 0
    } catch {
        return 0
    }
}

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

    shouldWriteForTeam(teamId: number): boolean {
        return (
            this.config.mode === 'enabled' &&
            !this.config.excludedTeams.includes(teamId) &&
            (this.config.teams === '*' || this.config.teams.includes(teamId))
        )
    }
}

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
