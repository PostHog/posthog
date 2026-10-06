import { parseTeamsList } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { buildTeamGate } from '~/ingestion/common/team-gate'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { FlagEvaluationsMode, Team, ValueMatcher } from '~/types'

export interface FlagEvaluationsConfig {
    /** '*' for all teams, or an explicit allowlist of team IDs. */
    teams: number[] | '*'
    /** Escape hatch: teams never forked, even when `teams` is '*'. */
    excludedTeams: number[]
    /** Keeps the events writes for teams on FLAG_EVALUATIONS_ONLY. */
    flagEvaluationsOnlyDisabled: boolean
}

/**
 * Gate for the $feature_flag_called fork that writes flag evaluations to the
 * ClickHouse flag_evaluations table (via the clickhouse_flag_evaluations
 * topic). The event continues to the events table unless the team's
 * organization is on FLAG_EVALUATIONS_ONLY.
 *
 * The fork write is never load-bearing for a dual-written event, but the batch
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
    private flagEvaluationsOnlyDisabled: boolean

    constructor(config: FlagEvaluationsConfig) {
        this.isEnabled = buildTeamGate(config.teams, config.excludedTeams)
        this.flagEvaluationsOnlyDisabled = config.flagEvaluationsOnlyDisabled
    }

    isEnabledForTeam(teamId: number): boolean {
        return this.isEnabled(teamId)
    }

    stopsEventsWritesFor(team: Pick<Team, 'flag_evaluations_mode'>): boolean {
        return (
            team.flag_evaluations_mode === FlagEvaluationsMode.FlagEvaluationsOnly && !this.flagEvaluationsOnlyDisabled
        )
    }
}

export type FlagEvaluationsEnvConfig = Pick<
    IngestionConsumerConfig,
    | 'INGESTION_FLAG_EVALUATIONS_MODE'
    | 'INGESTION_FLAG_EVALUATIONS_TEAMS'
    | 'INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS'
    | 'INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED'
> &
    Pick<IngestionOutputsConfig, 'INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC'>

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
    return new FlagEvaluationsService({
        teams,
        excludedTeams,
        flagEvaluationsOnlyDisabled: envConfig.INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED,
    })
}
