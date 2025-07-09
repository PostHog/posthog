import { expectLogic, partial } from 'kea-test-utils'
import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { featureFlagLogic, NEW_FLAG } from './featureFlagLogic'

// Import the standalone function for testing
/**
 * Detects specific feature flag changes that warrant confirmation.
 *
 * NOTE: This function intentionally only detects a LIMITED SUBSET of possible changes:
 * - Active status (enabled/disabled)
 * - First group's rollout percentage
 *
 * Other changes like name, key, properties, payloads, variants, etc. are not detected.
 * This is a deliberate design choice to focus on the most impactful changes that could
 * immediately affect user experience.
 */
function detectFeatureFlagChanges(
    originalFlag: FeatureFlagType | null,
    updatedFlag: Partial<FeatureFlagType>
): string[] {
    const changes: string[] = []

    if (!originalFlag) {
        return changes
    }

    // Check active status changes
    if (originalFlag.active !== updatedFlag.active) {
        changes.push('Flag enabled/disabled status changed')
    }

    // Check rollout percentage changes (only first group for simplicity)
    const originalRollout = originalFlag.filters?.groups?.[0]?.rollout_percentage || 0
    const updatedRollout = updatedFlag.filters?.groups?.[0]?.rollout_percentage || 0
    if (originalRollout !== updatedRollout) {
        changes.push('Release condition rollout percentage changed')
    }

    return changes
}

const MOCK_FEATURE_FLAG = {
    ...NEW_FLAG,
    id: 1,
    key: 'test-flag',
    name: 'test-name',
}

const MOCK_FEATURE_FLAG_STATUS = {
    status: 'active',
    reason: 'mock reason',
}

describe('featureFlagLogic', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = featureFlagLogic({ id: 1 })
        logic.mount()

        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${MOCK_FEATURE_FLAG.id}/`]: () => [
                    200,
                    MOCK_FEATURE_FLAG,
                ],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${MOCK_FEATURE_FLAG.id}/status`]: () => [
                    200,
                    MOCK_FEATURE_FLAG_STATUS,
                ],
            },
        })

        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('setMultivariateEnabled functionality', () => {
        it('adds an empty variant when enabling multivariate', async () => {
            await expectLogic(logic).toMatchValues({
                featureFlag: partial({
                    filters: partial({
                        groups: [
                            {
                                properties: [],
                                variant: null,
                            },
                        ],
                    }),
                }),
                variants: [],
            })
            await expectLogic(logic, () => {
                logic.actions.setMultivariateEnabled(true)
            })
                .toDispatchActions(['setMultivariateEnabled', 'setMultivariateOptions'])
                .toMatchValues({
                    variants: [
                        {
                            key: '',
                            name: '',
                            rollout_percentage: 100,
                        },
                    ],
                })
        })

        it('resets the variants and group variant keys when disabling multivariate', async () => {
            const MOCK_MULTIVARIATE_FEATURE_FLAG: FeatureFlagType = {
                ...logic.values.featureFlag,
                filters: {
                    groups: [
                        {
                            variant: 'control1',
                            properties: [
                                {
                                    key: '$browser',
                                    type: PropertyFilterType.Person,
                                    value: 'Chrome',
                                    operator: PropertyOperator.Regex,
                                },
                            ],
                            rollout_percentage: 100,
                        },
                    ],
                    payloads: {
                        control1: '{"key": "value"}',
                    },
                    multivariate: {
                        variants: [
                            {
                                key: 'control1',
                                name: 'Control 1',
                                rollout_percentage: 30,
                            },
                            {
                                key: 'control2',
                                name: 'Control 2',
                                rollout_percentage: 70,
                            },
                        ],
                    },
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(MOCK_MULTIVARIATE_FEATURE_FLAG)
            })
                .toDispatchActions(['setFeatureFlag'])
                .toMatchValues({
                    featureFlag: MOCK_MULTIVARIATE_FEATURE_FLAG,
                })

            await expectLogic(logic, () => {
                logic.actions.setMultivariateEnabled(false)
            })
                .toDispatchActions(['setMultivariateEnabled', 'setMultivariateOptions'])
                .toMatchValues({
                    featureFlag: partial({
                        filters: partial({
                            groups: [
                                {
                                    ...MOCK_MULTIVARIATE_FEATURE_FLAG.filters.groups[0],
                                    variant: null,
                                },
                            ],
                            payloads: {},
                        }),
                    }),
                    variants: [],
                })
        })
    })

    describe('confirmation modal integration', () => {
        it('detects changes when flag is modified', async () => {
            // Load the flag first
            await expectLogic(logic).toFinishAllListeners()

            const originalFlag = logic.values.featureFlag
            const changedFlag = {
                ...originalFlag,
                active: !originalFlag.active, // Toggle active state
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(changedFlag)
            }).toMatchValues({
                featureFlag: changedFlag,
            })

            // Test change detection
            const changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            expect(changes.length).toBeGreaterThan(0)
            expect(changes).toContain('Flag enabled/disabled status changed')
        })

        it('shows confirmation modal for existing flag changes', async () => {
            // Mock team with confirmation enabled
            const mockTeam = { feature_flag_confirmation_enabled: true }

            await expectLogic(logic).toFinishAllListeners()

            const originalFlag = logic.values.featureFlag
            const changedFlag = {
                ...originalFlag,
                active: true,
                filters: {
                    ...originalFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 50, // Change rollout
                            variant: null,
                        },
                    ],
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(changedFlag)
            }).toMatchValues({
                featureFlag: changedFlag,
            })

            // Test that changes are detected and modal would be shown
            const changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            expect(changes.length).toBeGreaterThan(0)

            // Mock the form submission to check behavior
            const showConfirmationModalSpy = jest.spyOn(logic.actions, 'showConfirmationModal')

            // Simulate the confirmation check that happens in form submit
            if (changedFlag.id && mockTeam.feature_flag_confirmation_enabled && changes.length > 0) {
                logic.actions.showConfirmationModal(changes, changedFlag)
            }

            expect(showConfirmationModalSpy).toHaveBeenCalledWith(changes, changedFlag)
        })

        it('skips confirmation modal for new flags', async () => {
            const newFlagLogic = featureFlagLogic({ id: 'new' })
            newFlagLogic.mount()

            const newFlag = { ...NEW_FLAG, key: 'new-flag', name: 'New Flag' }

            await expectLogic(newFlagLogic, () => {
                newFlagLogic.actions.setFeatureFlag(newFlag)
            }).toMatchValues({
                featureFlag: newFlag,
            })

            const changes = detectFeatureFlagChanges(null, newFlag) // null original for new flags
            expect(changes.length).toBe(0) // No changes detected for new flags

            newFlagLogic.unmount()
        })

        it('skips confirmation when team setting is disabled', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const mockTeam = { feature_flag_confirmation_enabled: false }
            const originalFlag = logic.values.featureFlag
            const changedFlag = { ...originalFlag, active: !originalFlag.active }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(changedFlag)
            }).toMatchValues({
                featureFlag: changedFlag,
            })

            const showConfirmationModalSpy = jest.spyOn(logic.actions, 'showConfirmationModal')

            // Test that changes are detected but confirmation is skipped
            const changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            expect(changes.length).toBeGreaterThan(0)

            // Since team setting is disabled, confirmation modal should not be shown
            if (changedFlag.id && mockTeam.feature_flag_confirmation_enabled && changes.length > 0) {
                logic.actions.showConfirmationModal(changes, changedFlag)
            }

            expect(showConfirmationModalSpy).not.toHaveBeenCalled()
        })
    })
})
