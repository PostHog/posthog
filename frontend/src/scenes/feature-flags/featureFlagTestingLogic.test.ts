import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
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

    describe('setSelectedPerson', () => {
        it.each([
            {
                description: 'stores a full person (from Persons tab)',
                person: { name: 'Jane Doe', uuid: 'uuid-abc', distinct_ids: ['user-123'] },
                expected: { name: 'Jane Doe', uuid: 'uuid-abc', distinct_ids: ['user-123'] },
            },
            {
                description: 'stores a partial person (from recent tab — name only, no uuid or distinct_ids)',
                person: { name: 'Jane Doe' },
                expected: { name: 'Jane Doe' },
            },
        ])('$description', async ({ person, expected }) => {
            await expectLogic(logic, () => {
                logic.actions.setSelectedPerson(person)
            }).toMatchValues({ selectedPerson: expected })
        })
    })

    describe('distinct ID bucketing selectors', () => {
        it.each([
            {
                description: 'full person with multiple merged IDs flags as having multiple',
                person: { name: 'Jane Doe', uuid: 'uuid-abc', distinct_ids: ['user-123', 'user-456'] },
                expectedDistinctIds: ['user-123', 'user-456'],
                expectedHasMultiple: true,
            },
            {
                description: 'full person with a single ID does not flag as having multiple',
                person: { name: 'Jane Doe', uuid: 'uuid-abc', distinct_ids: ['user-123'] },
                expectedDistinctIds: ['user-123'],
                expectedHasMultiple: false,
            },
            {
                description: 'partial person (no distinct_ids) yields an empty list before async resolve',
                person: { name: 'Jane Doe' },
                expectedDistinctIds: [],
                expectedHasMultiple: false,
            },
            {
                description: 'no selected person yields an empty list',
                person: null,
                expectedDistinctIds: [],
                expectedHasMultiple: false,
            },
        ])('$description', async ({ person, expectedDistinctIds, expectedHasMultiple }) => {
            await expectLogic(logic, () => {
                logic.actions.setSelectedPerson(person)
            }).toMatchValues({
                personDistinctIds: expectedDistinctIds,
                hasMultipleDistinctIds: expectedHasMultiple,
            })
        })

        it('resolves distinct IDs for a partial person (recent tab) via the persons API', async () => {
            useMocks({
                get: {
                    '/api/environments/:team/persons/': () => [
                        200,
                        { results: [{ distinct_ids: ['user-123', 'user-456'] }], count: 1 },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setSelectedPerson({ name: 'Jane Doe' }, 'user-123')
            })
                .toFinishAllListeners()
                .toMatchValues({
                    personDistinctIds: ['user-123', 'user-456'],
                    hasMultipleDistinctIds: true,
                })
        })

        it('clears resolved distinct IDs when a new person is selected', async () => {
            useMocks({
                get: {
                    '/api/environments/:team/persons/': () => [
                        200,
                        { results: [{ distinct_ids: ['user-123', 'user-456'] }], count: 1 },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setSelectedPerson({ name: 'Jane Doe' }, 'user-123')
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setSelectedPerson(null)
            }).toMatchValues({ personDistinctIds: [], hasMultipleDistinctIds: false })
        })
    })

    describe('bucketingDistinctId selector', () => {
        const baseResult: Omit<FeatureFlagTestEvaluationResponseApi, 'evaluation_distinct_id'> = {
            flag_key: 'test-flag',
            result: true,
            reason: 'condition_match',
            condition_index: 0,
            payload: null,
            person_properties: {},
            conditions: [],
        }

        it('is null before any evaluation has run', () => {
            expect(logic.values.bucketingDistinctId).toBeNull()
        })

        it.each([
            {
                description: 'returns the backend-reported ID when present',
                evaluation_distinct_id: 'user-123',
                expected: 'user-123',
            },
            {
                description: 'is null when the backend withholds it (a different ID was used)',
                evaluation_distinct_id: null,
                expected: null,
            },
        ])('$description', async ({ evaluation_distinct_id, expected }) => {
            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess({
                    ...baseResult,
                    evaluation_distinct_id,
                })
            }).toMatchValues({ bucketingDistinctId: expected })
        })

        it('resets to null when setTestFormData is dispatched after a successful evaluation', async () => {
            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess({
                    ...baseResult,
                    evaluation_distinct_id: 'user-123',
                })
            }).toMatchValues({ bucketingDistinctId: 'user-123' })

            await expectLogic(logic, () => {
                logic.actions.setTestFormData({ distinct_id: 'user-456' })
            }).toMatchValues({ bucketingDistinctId: null })
        })
    })

    describe('hasValidPerson selector', () => {
        it.each([
            { description: 'is true when distinct_id is set', formData: { distinct_id: 'user-123' }, expected: true },
            { description: 'is false when distinct_id is empty', formData: {}, expected: false },
        ])('$description', async ({ formData, expected }) => {
            await expectLogic(logic, () => {
                logic.actions.setTestFormData(formData)
            }).toMatchValues({ hasValidPerson: expected })
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

    describe('testFlagEvaluation person identifier', () => {
        it.each([
            {
                description: 'sends distinct_id when set',
                formData: { distinct_id: 'user-123', timestamp: '', groups: '' },
                expectedBody: { distinct_id: 'user-123' },
            },
            {
                description: 'omits distinct_id when empty',
                formData: { distinct_id: '', timestamp: '', groups: '' },
                expectedBody: {},
            },
        ])('$description', async ({ formData, expectedBody }) => {
            let capturedBody: Record<string, any> = {}
            useMocks({
                post: {
                    '/api/projects/:team/feature_flags/1/test_evaluation': async ({ request }) => {
                        capturedBody = (await request.json()) as Record<string, any>
                        return [200, {}]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluation({ flagId: 1, formData })
            }).toFinishAllListeners()

            expect(capturedBody).toMatchObject(expectedBody)
            expect(capturedBody).not.toHaveProperty('person_id')
        })
    })

    describe('groups validation through testFlagEvaluation', () => {
        // The invalid-groups cases fail the evaluation loader on purpose; kea-loaders would log each
        beforeEach(silenceKeaLoadersErrors)
        afterEach(resumeKeaLoadersErrors)

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
                    formData: { distinct_id: 'p1', timestamp: '', groups },
                })
            }).toFinishAllListeners()

            expect(logic.values.testError).toBe(expectedError)
        })
    })
})
