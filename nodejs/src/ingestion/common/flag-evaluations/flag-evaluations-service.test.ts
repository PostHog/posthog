import { FlagEvaluationsMode } from '~/types'

import { FlagEvaluationsEnvConfig, createFlagEvaluationsService } from './flag-evaluations-service'

describe('FlagEvaluationsService', () => {
    const envConfig = (
        mode: string,
        teams = '*',
        excludedTeams = '',
        topic = 'clickhouse_flag_evaluations'
    ): FlagEvaluationsEnvConfig => ({
        INGESTION_FLAG_EVALUATIONS_MODE: mode,
        INGESTION_FLAG_EVALUATIONS_TEAMS: teams,
        INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS: excludedTeams,
        INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED: false,
        INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC: topic,
        INGESTION_OUTPUT_REALTIME_ONLY_EVENTS_TOPIC: '',
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

    describe('stopsEventsWritesFor', () => {
        it.each([
            [false, true],
            [true, false],
        ])(
            'INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED=%s -> %s for a FLAG_EVALUATIONS_ONLY team',
            (onlyDisabled, expected) => {
                const service = createFlagEvaluationsService({
                    ...envConfig('dual_write'),
                    INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED: onlyDisabled,
                })

                expect(
                    service?.stopsEventsWritesFor({ flag_evaluations_mode: FlagEvaluationsMode.FlagEvaluationsOnly })
                ).toBe(expected)
            }
        )
    })

    describe('routesToRealtimeOnlyEvents', () => {
        it.each([
            ['realtime_only_events_json', true],
            ['', false],
        ])('INGESTION_OUTPUT_REALTIME_ONLY_EVENTS_TOPIC=%j -> %s', (topic, expected) => {
            const service = createFlagEvaluationsService({
                ...envConfig('dual_write'),
                INGESTION_OUTPUT_REALTIME_ONLY_EVENTS_TOPIC: topic,
            })

            expect(service?.routesToRealtimeOnlyEvents).toBe(expected)
        })
    })
})
