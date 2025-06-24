import { expectLogic } from 'kea-test-utils'
import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'
import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagsFilters, featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagReleaseType, FeatureFlagType } from '~/types'

import { relatedFeatureFlagsLogic } from './relatedFeatureFlagsLogic'

const createMockFlag = (overrides: Partial<FeatureFlagType>): FeatureFlagType => ({
    ...NEW_FLAG,
    created_at: '2023-01-01T00:00:00Z',
    ...overrides,
})

const MOCK_FLAGS: FeatureFlagType[] = [
    createMockFlag({
        id: 1,
        key: 'flag-1',
        name: 'Flag 1',
        active: true,
        rollout_percentage: 100,
    }),
    createMockFlag({
        id: 2,
        key: 'flag-2',
        name: 'Flag 2',
        active: false,
        rollout_percentage: 100,
    }),
    createMockFlag({
        id: 3,
        key: 'flag-3',
        name: 'Flag 3',
        active: true,
        filters: {
            ...NEW_FLAG.filters,
            multivariate: { variants: [{ key: 'a', rollout_percentage: 100 }] },
        },
        rollout_percentage: null,
    }),
]

const MOCK_EVALUATION_REASONS = {
    'flag-1': { value: true, evaluation: { reason: 'condition_match', condition_index: 0 } },
    'flag-2': { value: false, evaluation: { reason: 'no_condition_match' } },
    'flag-3': { value: true, evaluation: { reason: 'condition_match', condition_index: 1 } },
}

describe('relatedFeatureFlagsLogic', () => {
    let logic: ReturnType<typeof relatedFeatureFlagsLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        flagsLogic?.unmount()
    })

    describe('server-side filtering', () => {
        const setupMocks = (filters?: FeatureFlagsFilters): void => {
            const queryParams = filters ? `?${new URLSearchParams(filters as any).toString()}` : ''

            // Filter flags based on provided filters
            let filteredFlags = [...MOCK_FLAGS]
            if (filters?.active !== undefined) {
                const isActive = filters.active === 'true'
                filteredFlags = filteredFlags.filter((flag) => flag.active === isActive)
            }
            if (filters?.type) {
                if (filters.type === 'boolean') {
                    filteredFlags = filteredFlags.filter((flag) => !flag.filters.multivariate?.variants?.length)
                } else if (filters.type === 'multivariant') {
                    filteredFlags = filteredFlags.filter((flag) => !!flag.filters.multivariate?.variants?.length)
                }
            }

            // eslint-disable-next-line react-hooks/rules-of-hooks
            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${queryParams}`]: {
                        results: filteredFlags,
                        count: filteredFlags.length,
                    },
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/evaluation_reasons`]:
                        MOCK_EVALUATION_REASONS,
                },
            })
        }

        beforeEach(() => {
            setupMocks()
            flagsLogic = featureFlagsLogic()
            flagsLogic.mount()
            logic = relatedFeatureFlagsLogic({ distinctId: 'test-user' })
            logic.mount()
        })

        it('should filter flags by type=boolean on server side', async () => {
            setupMocks({ type: 'boolean', page: 1 })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(2)
            expect(flagsLogic.values.featureFlags.results.map((f) => f.key)).toEqual(['flag-1', 'flag-2'])

            expect(logic.values.mappedRelatedFeatureFlags).toHaveLength(2)
            expect(logic.values.mappedRelatedFeatureFlags.map((f) => f.key)).toEqual(['flag-1', 'flag-2'])
        })

        it('should filter flags by type=multivariant on server side', async () => {
            setupMocks({ type: 'multivariant', page: 1 })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.Variants })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(1)
            expect(flagsLogic.values.featureFlags.results[0].key).toEqual('flag-3')

            expect(logic.values.mappedRelatedFeatureFlags).toHaveLength(1)
            expect(logic.values.mappedRelatedFeatureFlags[0].key).toEqual('flag-3')
        })

        it('should filter flags by active=true on server side', async () => {
            setupMocks({ active: 'true', page: 1 })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(2)
            expect(flagsLogic.values.featureFlags.results.map((f) => f.key)).toEqual(['flag-1', 'flag-3'])

            expect(flagsLogic.values.featureFlags.results.every((f) => f.active)).toBe(true)
        })

        it('should filter flags by active=false on server side', async () => {
            setupMocks({ active: 'false', page: 1 })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'false' })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(1)
            expect(flagsLogic.values.featureFlags.results[0].key).toEqual('flag-2')
            expect(flagsLogic.values.featureFlags.results[0].active).toBe(false)
        })

        it('should combine multiple filters', async () => {
            setupMocks({ type: 'boolean', active: 'true', page: 1 })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(1)
            expect(flagsLogic.values.featureFlags.results[0].key).toEqual('flag-1')
        })

        it('should clear type filter when replace=true and type not in new filters', async () => {
            setupMocks({ type: 'boolean', active: 'true', page: 1 })
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            }).toFinishAllListeners()

            setupMocks({ active: 'true', page: 1 })
            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' }, true)
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(2)
            expect(flagsLogic.values.featureFlags.results.map((f) => f.key)).toEqual(['flag-1', 'flag-3'])
        })

        it('should still apply client-side filtering for reason filter', async () => {
            setupMocks()
            await expectLogic(flagsLogic).toFinishAllListeners()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ reason: 'condition_match' })
            })

            const filtered = logic.values.filteredMappedFlags
            expect(filtered).toHaveLength(2)
            expect(filtered.map((f) => f.key)).toEqual(['flag-1', 'flag-3'])
        })

        it('should reload evaluation reasons when feature flags are reloaded', async () => {
            setupMocks()
            await expectLogic(logic).toFinishAllListeners()

            const loadRelatedFeatureFlagsSpy = jest.spyOn(logic.actions, 'loadRelatedFeatureFlags')

            flagsLogic.actions.loadFeatureFlagsSuccess({ results: MOCK_FLAGS, count: MOCK_FLAGS.length })

            await expectLogic(logic).toFinishAllListeners()

            expect(loadRelatedFeatureFlagsSpy).toHaveBeenCalled()
        })
    })
})
