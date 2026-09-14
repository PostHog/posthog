import { IngestionLane } from '~/ingestion/config'

import { FlagEvaluationsEnvConfig, createFlagEvaluationsService } from './flag-evaluations-service'

describe('FlagEvaluationsService', () => {
    const envConfig = (
        mode: string,
        teams = '*',
        excludedTeams = '',
        topic = 'clickhouse_flag_evaluations',
        lane: IngestionLane | null = 'main'
    ): FlagEvaluationsEnvConfig => ({
        INGESTION_LANE: lane,
        INGESTION_FLAG_EVALUATIONS_MODE: mode,
        INGESTION_FLAG_EVALUATIONS_TEAMS: teams,
        INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS: excludedTeams,
        INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC: topic,
    })

    describe('createFlagEvaluationsService', () => {
        // The wildcard-exclusion case is the escape hatch: it must fail toward the
        // events table, not toward excluding everyone from being excluded. The
        // empty-topic case guards the fork from producing into a nameless topic.
        it.each([
            ['mode is disabled', envConfig('disabled'), false],
            ['mode is invalid', envConfig('garbage'), false],
            ['the output topic is empty', envConfig('dual_write', '*', '', ''), false],
            ['excluded teams is the wildcard', envConfig('dual_write', '*', '*'), false],
            ['mode is dual_write', envConfig('dual_write'), true],
            // The backfill owns history, so a delayed lane must never fork even
            // when the env vars say dual_write.
            ['the lane is historical', envConfig('dual_write', '*', '', 'topic', 'historical'), false],
            ['the lane is async', envConfig('dual_write', '*', '', 'topic', 'async'), false],
            ['the lane is overflow', envConfig('dual_write', '*', '', 'topic', 'overflow'), true],
            ['no lane is set (local dev)', envConfig('dual_write', '*', '', 'topic', null), true],
            ['the teams allowlist is empty', envConfig('dual_write', ''), false],
        ])('builds a service when %s -> %s', (_name, config, expected) => {
            expect(createFlagEvaluationsService(config) !== undefined).toBe(expected)
        })
    })

    describe('isEnabledForTeam', () => {
        it.each([
            ['*', '', 5, true],
            ['*', '5', 5, false],
            ['1,2', '', 2, true],
            ['1,2', '', 3, false],
            ['1,2', '2', 2, false],
        ])('teams=%s excluded=%s team=%i -> %s', (teams, excluded, teamId, expected) => {
            const service = createFlagEvaluationsService(envConfig('dual_write', teams, excluded))

            expect(service?.isEnabledForTeam(teamId)).toBe(expected)
        })
    })
})
