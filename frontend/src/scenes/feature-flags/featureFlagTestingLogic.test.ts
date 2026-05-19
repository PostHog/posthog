import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
            const mockResult = {
                flagMatch: true,
                flagValue: 'test-variant',
                condition_index: 1,
                conditions: [
                    {
                        index: 0,
                        properties_matched: true,
                        matched: false,
                        rollout_excluded: false,
                    },
                    {
                        index: 1,
                        properties_matched: true,
                        matched: true,
                        rollout_excluded: false,
                    },
                    {
                        index: 2,
                        properties_matched: false,
                        matched: false,
                        rollout_excluded: false,
                    },
                ],
            }

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess(mockResult as any)
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
            const mockResult = {
                flagMatch: false,
                flagValue: null,
                condition_index: -1,
                conditions: [
                    {
                        index: 0,
                        properties_matched: true,
                        matched: false,
                        rollout_excluded: true, // excluded from rollout
                    },
                ],
            }

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess(mockResult as any)
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
            const mockResult = {
                result: false,
                reason: 'no_condition_match',
                condition_index: 1, // Points to last condition but result is false
                conditions: [
                    {
                        index: 0,
                        properties_matched: false,
                        matched: false,
                        rollout_excluded: false,
                    },
                    {
                        index: 1,
                        properties_matched: false,
                        matched: false,
                        rollout_excluded: false,
                    },
                ],
            }

            await expectLogic(logic, () => {
                logic.actions.testFlagEvaluationSuccess(mockResult as any)
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
})
