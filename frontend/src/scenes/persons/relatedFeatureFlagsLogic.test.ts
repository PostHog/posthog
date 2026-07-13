import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

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
    }),
    createMockFlag({
        id: 2,
        key: 'flag-2',
        name: 'Flag 2',
        active: false,
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
        // One handler that filters by the request's actual query params — MSW ignores
        // query strings in handler URLs, so pre-baked per-filter handlers never keyed
        // off the params anyway.
        const setupMocks = (): void => {
            // oxlint-disable-next-line react-hooks/rules-of-hooks
            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/`]: ({ request }) => {
                        const params = new URL(request.url).searchParams
                        const active = params.get('active')
                        const type = params.get('type')
                        let filteredFlags = [...MOCK_FLAGS]
                        if (active !== null) {
                            filteredFlags = filteredFlags.filter((flag) => flag.active === (active === 'true'))
                        }
                        if (type === 'boolean') {
                            filteredFlags = filteredFlags.filter((flag) => !flag.filters.multivariate?.variants?.length)
                        } else if (type === 'multivariant') {
                            filteredFlags = filteredFlags.filter(
                                (flag) => !!flag.filters.multivariate?.variants?.length
                            )
                        }
                        return [200, { results: filteredFlags, count: filteredFlags.length }]
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
            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(2)
            expect(flagsLogic.values.featureFlags.results.map((f) => f.key)).toEqual(['flag-1', 'flag-3'])

            expect(flagsLogic.values.featureFlags.results.every((f) => f.active)).toBe(true)
        })

        it('should filter flags by active=false on server side', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'false' })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(1)
            expect(flagsLogic.values.featureFlags.results[0].key).toEqual('flag-2')
            expect(flagsLogic.values.featureFlags.results[0].active).toBe(false)
        })

        it('should combine multiple filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            }).toFinishAllListeners()

            await expectLogic(flagsLogic).toFinishAllListeners()

            expect(flagsLogic.values.featureFlags.results).toHaveLength(1)
            expect(flagsLogic.values.featureFlags.results[0].key).toEqual('flag-1')
        })

        it('should clear type filter when replace=true and type not in new filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            }).toFinishAllListeners()

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

            await expectLogic(flagsLogic, () => {
                logic.actions.loadRelatedFeatureFlags()
            })
                .toDispatchActions(['loadFeatureFlags'])
                .toFinishAllListeners()

            await expectLogic(logic).toFinishAllListeners()
        })
    })
})
