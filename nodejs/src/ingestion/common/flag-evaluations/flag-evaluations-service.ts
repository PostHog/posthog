import { parseTeamsList } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { buildTeamGate } from '~/ingestion/common/team-gate'
import {
    IngestionConsumerConfig,
    IngestionLane,
    IngestionOutputsConfig,
    REALTIME_INGESTION_LANES,
} from '~/ingestion/config'
import { ValueMatcher } from '~/types'

export interface FlagEvaluationsConfig {
    /** '*' for all teams, or an explicit allowlist of team IDs. */
    teams: number[] | '*'
    /** Escape hatch: teams never forked, even when `teams` is '*'. */
    excludedTeams: number[]
}

/**
 * Gate for the $feature_flag_called fork that shadow-writes flag evaluations to
 * the ClickHouse flag_evaluations table (via the clickhouse_flag_evaluations
 * topic) while the event continues to the events table unchanged.
 *
 * The shadow write is never load-bearing for an individual event, but the batch
 * does not commit its offsets until the broker answers. See
 * createForkFlagEvaluationsStep for the ack contract and
 * flagEvaluationsPendingAcks for the stall it can cause.
 *
 * Shedding that dependency during an incident takes BOTH env vars, not just the
 * mode: the mode stops a running consumer from forking, but startup topic
 * verification is driven by the output registration, which the mode does not
 * touch. A pod that restarts with INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC still
 * set fails to start at all while the topic is unreachable. Clear the topic too.
 */
export class FlagEvaluationsService {
    private isEnabled: ValueMatcher<number>

    constructor(config: FlagEvaluationsConfig) {
        this.isEnabled = buildTeamGate(config.teams, config.excludedTeams)
    }

    isEnabledForTeam(teamId: number): boolean {
        return this.isEnabled(teamId)
    }
}

export type FlagEvaluationsEnvConfig = Pick<
    IngestionConsumerConfig,
    | 'INGESTION_LANE'
    | 'INGESTION_FLAG_EVALUATIONS_MODE'
    | 'INGESTION_FLAG_EVALUATIONS_TEAMS'
    | 'INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS'
> &
    Pick<IngestionOutputsConfig, 'INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC'>

/**
 * Lanes that may fork: the real-time lanes plus `null` for local dev, where no
 * lane is set. Derived from REALTIME_INGESTION_LANES so a new real-time lane is
 * covered automatically; delayed lanes are excluded by construction.
 *
 * The backfill owns history for this table, so a delayed lane that also forked
 * would write rows the backfill already covers, double-counting the per-flag
 * usage the table exists to answer. The gate holds even if the env vars leak
 * into a config shared across lanes.
 */
const FLAG_EVALUATIONS_ALLOWED_LANES: readonly (IngestionLane | null)[] = [...REALTIME_INGESTION_LANES, null]

/**
 * Builds the flag evaluations service, or undefined when the fork is off. The
 * pipeline composes the fork step out entirely when this returns undefined.
 */
export function createFlagEvaluationsService(envConfig: FlagEvaluationsEnvConfig): FlagEvaluationsService | undefined {
    const mode = envConfig.INGESTION_FLAG_EVALUATIONS_MODE
    if (mode !== 'dual_write') {
        if (mode !== 'disabled') {
            logger.warn('Invalid INGESTION_FLAG_EVALUATIONS_MODE, falling back to disabled', { mode })
        }
        return undefined
    }
    if (!envConfig.INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC) {
        // An empty topic also skips the startup topic-existence check, so producing
        // here would fail at runtime instead. See the enable ordering in config.ts.
        logger.warn(
            'INGESTION_FLAG_EVALUATIONS_MODE is set but INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC is empty, not forking'
        )
        return undefined
    }
    if (!FLAG_EVALUATIONS_ALLOWED_LANES.includes(envConfig.INGESTION_LANE)) {
        logger.warn('Flag evaluations fork is not supported on this ingestion lane, disabling', {
            lane: envConfig.INGESTION_LANE,
        })
        return undefined
    }
    const excludedTeams = parseTeamsList(envConfig.INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS)
    if (excludedTeams === '*') {
        // An operator's '*' exclusion means "off": the escape hatch fails toward not forking.
        logger.warn('INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS is "*", disabling the flag evaluations fork')
        return undefined
    }
    const teams = parseTeamsList(envConfig.INGESTION_FLAG_EVALUATIONS_TEAMS)
    if (teams !== '*' && teams.length === 0) {
        // Same shape as the empty-topic case: an allowlist naming nobody is off, so
        // compose the step out rather than paying it per event to gate every team away.
        logger.warn('INGESTION_FLAG_EVALUATIONS_MODE is set but INGESTION_FLAG_EVALUATIONS_TEAMS is empty, not forking')
        return undefined
    }
    return new FlagEvaluationsService({ teams, excludedTeams })
}
