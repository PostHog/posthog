import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { FeatureFlagTestEvaluationResponseApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { featureFlagTestingLogic, resolvePersonSelection } from './featureFlagTestingLogic'

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
                logic.actions.testFlagEvaluationSuccess(mockResult as FeatureFlagTestEvaluationResponseApi)
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
                logic.actions.testFlagEvaluationSuccess(mockResult as FeatureFlagTestEvaluationResponseApi)
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
                logic.actions.testFlagEvaluationSuccess(mockResult as FeatureFlagTestEvaluationResponseApi)
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

    describe('groups validation through testFlagEvaluation', () => {
        it.each([
            { description: 'valid object succeeds', groups: '{"team": "backend"}', expectedError: null },
            { description: 'empty string succeeds', groups: '', expectedError: null },
            { description: 'whitespace succeeds', groups: '   \n\t   ', expectedError: null },
            { description: 'array fails', groups: '["team","backend"]', expectedError: 'groups must be a JSON object' },
            {
                description: 'invalid JSON fails',
                groups: '{invalid: json}',
                expectedError: 'Invalid JSON format for groups',
            },
            {
                description: 'json string fails',
                groups: '"just a string"',
                expectedError: 'groups must be a JSON object',
            },
            { description: 'json number fails', groups: '42', expectedError: 'groups must be a JSON object' },
        ])('$description', async ({ groups, expectedError }) => {
            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluation({
                    flagId: 1,
                    formData: { person_id: 'p1', distinct_id: '', timestamp: '', groups },
                })
            }).toFinishAllListeners()

            expect(logic.values.testError).toBe(expectedError)
        })
    })

    describe('resolvePersonSelection', () => {
        it('resolves a full person from the Persons tab using uuid and distinct_ids', () => {
            const person = { uuid: 'person-uuid', name: 'Jane', distinct_ids: ['d1', 'd2'] }
            expect(resolvePersonSelection('d1', person)).toEqual({
                person: expect.objectContaining({ uuid: 'person-uuid', distinct_ids: ['d1', 'd2'] }),
                personId: 'person-uuid',
                distinctId: 'd1',
            })
        })

        it('resolves a stripped Recent-tab item via its recent context (no uuid/distinct_ids)', () => {
            // Recent-tab entries only carry { name, _recentContext } — reading distinct_ids[0] used to throw
            const recentItem = {
                name: 'a@b.co',
                _recentContext: { sourceGroupType: 'persons', sourceGroupName: 'Persons', sourceValue: 'd-recent' },
            }
            expect(resolvePersonSelection(null, recentItem)).toEqual({
                person: expect.objectContaining({ name: 'a@b.co', distinct_ids: ['d-recent'] }),
                personId: '',
                distinctId: 'd-recent',
            })
        })

        it('returns null when no identifier can be resolved', () => {
            expect(resolvePersonSelection(null, { name: 'No IDs' })).toBeNull()
            expect(resolvePersonSelection(null, null)).toBeNull()
        })
    })

    describe('hasValidPerson selector', () => {
        it('is true when a person_id is set', () => {
            logic.actions.setTestFormData({ person_id: 'some-uuid' })
            expect(logic.values.hasValidPerson).toBe(true)
        })

        it('is true when only a distinct_id is set (e.g. recent-tab selection)', () => {
            logic.actions.setTestFormData({ distinct_id: 'distinct-1' })
            expect(logic.values.hasValidPerson).toBe(true)
        })

        it('is false when neither identifier is set', () => {
            expect(logic.values.hasValidPerson).toBe(false)
        })
    })
})
