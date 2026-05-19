import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { FeatureFlagTestEvaluationResponseApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { featureFlagTestingLogic } from './featureFlagTestingLogic'

describe('featureFlagTestingLogic', () => {
    let logic: ReturnType<typeof featureFlagTestingLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/feature_flags/1/test_evaluation': () => [200, {}],
            },
            post: {
                '/api/projects/:team/feature_flags/1/test_evaluation': () => [200, {}],
            },
        })
        initKeaTests()
        logic = featureFlagTestingLogic({ flagId: 1 })
        logic.mount()
    })

    describe('condition analysis', () => {
        it('correctly identifies matchedButNotWinner conditions', async () => {
            const mockResult: Partial<FeatureFlagTestEvaluationResponseApi> = {
                flag_key: 'test-flag',
                result: true,
                reason: 'condition_match',
                condition_index: 1,
                payload: null,
                person_properties: {},
                evaluation_distinct_id: null,
                conditions: [
                    {
                        index: 0,
                        properties_matched: true,
                        matched: false,
                        rollout_excluded: false,
                        explanation: 'Properties matched but condition was not winner',
                        rollout_percentage: 100,
                        variant: null,
                        properties: [],
                    },
                    {
                        index: 1,
                        properties_matched: true,
                        matched: true,
                        rollout_excluded: false,
                        explanation: 'Condition matched and won',
                        rollout_percentage: 100,
                        variant: 'test-variant',
                        properties: [],
                    },
                    {
                        index: 2,
                        properties_matched: false,
                        matched: false,
                        rollout_excluded: false,
                        explanation: 'Properties did not match',
                        rollout_percentage: 100,
                        variant: null,
                        properties: [],
                    },
                ],
            }

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess(mockResult)
            }).toMatchValues({
                enrichedConditions: [
                    expect.objectContaining({
                        index: 0,
                        matchedButNotWinner: true, // properties_matched=true, not winner, not rollout_excluded
                        isWinningCondition: false,
                        display: {
                            tone: 'info',
                            label: 'PROPERTIES MATCHED',
                        },
                    }),
                    expect.objectContaining({
                        index: 1,
                        matchedButNotWinner: false, // is the winner
                        isWinningCondition: true,
                        display: {
                            tone: 'success',
                            label: 'MATCHED',
                        },
                    }),
                    expect.objectContaining({
                        index: 2,
                        matchedButNotWinner: false, // properties_matched=false
                        isWinningCondition: false,
                        display: {
                            tone: 'muted',
                            label: null,
                        },
                    }),
                ],
            })
        })

        it('handles rollout_excluded conditions correctly', async () => {
            const mockResult: Partial<FeatureFlagTestEvaluationResponseApi> = {
                flag_key: 'test-flag',
                result: false,
                reason: 'rollout_excluded',
                condition_index: -1,
                payload: null,
                person_properties: {},
                evaluation_distinct_id: null,
                conditions: [
                    {
                        index: 0,
                        properties_matched: true,
                        matched: false,
                        rollout_excluded: true,
                        explanation: 'Properties matched but excluded from rollout',
                        rollout_percentage: 50,
                        variant: null,
                        properties: [],
                    },
                ],
            }

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess(mockResult)
            }).toMatchValues({
                enrichedConditions: [
                    expect.objectContaining({
                        index: 0,
                        matchedButNotWinner: false, // rollout_excluded=true
                        isWinningCondition: false,
                        display: {
                            tone: 'warning',
                            label: 'EXCLUDED FROM ROLLOUT',
                        },
                    }),
                ],
            })
        })

        it('does not show MATCHED when no conditions actually match', async () => {
            const mockResult: Partial<FeatureFlagTestEvaluationResponseApi> = {
                flag_key: 'test-flag',
                result: false,
                reason: 'no_condition_match',
                condition_index: 1, // Points to last condition but result is false
                payload: null,
                person_properties: {},
                evaluation_distinct_id: null,
                conditions: [
                    {
                        index: 0,
                        properties_matched: false,
                        matched: false,
                        rollout_excluded: false,
                        explanation: 'Properties did not match',
                        rollout_percentage: 100,
                        variant: null,
                        properties: [],
                    },
                    {
                        index: 1,
                        properties_matched: false,
                        matched: false,
                        rollout_excluded: false,
                        explanation: 'Properties did not match',
                        rollout_percentage: 100,
                        variant: null,
                        properties: [],
                    },
                ],
            }

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess(mockResult)
            }).toMatchValues({
                enrichedConditions: [
                    expect.objectContaining({
                        index: 0,
                        isWinningCondition: false,
                        display: {
                            tone: 'muted',
                            label: null,
                        },
                    }),
                    expect.objectContaining({
                        index: 1,
                        isWinningCondition: false, // Should not be winning even though condition_index=1
                        display: {
                            tone: 'muted',
                            label: null,
                        },
                    }),
                ],
            })
        })
    })

    describe('errorDisplay selector', () => {
        const errorTestCases = [
            {
                description: 'build person properties error',
                input: 'Failed to build person properties at specified timestamp',
                expected: {
                    message: 'Failed to build person properties at specified timestamp',
                    helpText:
                        'Try a more recent timestamp when this person was active, remove the timestamp to test with current person properties, or select a different person who was active at that time.',
                },
            },
            {
                description: 'timestamp error',
                input: 'Invalid timestamp format',
                expected: {
                    message: 'Invalid timestamp format',
                    helpText:
                        'When using historical timestamps, the person must have existed at that time and had the necessary properties for evaluation.',
                },
            },
            {
                description: 'person not found error',
                input: 'Person not found for distinct_id',
                expected: {
                    message: 'Person not found for distinct_id',
                    helpText: 'Try selecting a different person or removing the timestamp to test with current data.',
                },
            },
            {
                description: 'person not found error with timestamp (rewritten error message)',
                input: 'Person not found. This person may not have existed at the selected timestamp.',
                expected: {
                    message: 'Person not found. This person may not have existed at the selected timestamp.',
                    helpText: 'Try selecting a different person or removing the timestamp to test with current data.',
                },
            },
            {
                description: 'generic error without helpText',
                input: 'Some generic API error',
                expected: {
                    message: 'Some generic API error',
                    helpText: null,
                },
            },
            {
                description: 'null error returns null',
                input: null,
                expected: null,
            },
        ]

        it.each(errorTestCases)('$description', ({ input, expected }) => {
            logic.actions.setTestError(input as any)
            expect(logic.values.errorDisplay).toEqual(expected)
        })
    })

    describe('validateAndParseGroups', () => {
        // We need to access the private function for testing
        const validateAndParseGroups = (groups: string): Record<string, any> => {
            try {
                const trimmed = groups.trim()
                if (!trimmed) {
                    return {}
                }
                const parsed = JSON.parse(trimmed)
                if (typeof parsed !== 'object' || Array.isArray(parsed)) {
                    throw new Error('groups must be a JSON object')
                }
                return parsed
            } catch (e) {
                throw new Error(`Invalid groups JSON: ${e instanceof Error ? e.message : String(e)}`)
            }
        }

        const validateGroupsTestCases = [
            {
                description: 'empty string returns empty object',
                input: '',
                expected: {},
            },
            {
                description: 'whitespace string returns empty object',
                input: '   \n\t   ',
                expected: {},
            },
            {
                description: 'valid JSON object is parsed correctly',
                input: '{"team": "backend", "env": "prod"}',
                expected: { team: 'backend', env: 'prod' },
            },
            {
                description: 'valid nested JSON object is parsed correctly',
                input: '{"organization": {"id": 123, "name": "Acme Corp"}}',
                expected: { organization: { id: 123, name: 'Acme Corp' } },
            },
            {
                description: 'JSON array throws error',
                input: '["team", "backend"]',
                shouldThrow: true,
                expectedError: 'Invalid groups JSON: groups must be a JSON object',
            },
            {
                description: 'invalid JSON throws error',
                input: '{invalid: json}',
                shouldThrow: true,
                expectedError:
                    "Invalid groups JSON: Expected property name or '}' in JSON at position 1 (line 1 column 2)",
            },
            {
                description: 'non-object JSON (string) throws error',
                input: '"just a string"',
                shouldThrow: true,
                expectedError: 'Invalid groups JSON: groups must be a JSON object',
            },
            {
                description: 'non-object JSON (number) throws error',
                input: '42',
                shouldThrow: true,
                expectedError: 'Invalid groups JSON: groups must be a JSON object',
            },
        ]

        it.each(validateGroupsTestCases)('$description', ({ input, expected, shouldThrow, expectedError }) => {
            if (shouldThrow) {
                expect(() => validateAndParseGroups(input)).toThrow(expectedError)
            } else {
                expect(validateAndParseGroups(input)).toEqual(expected)
            }
        })
    })
})
