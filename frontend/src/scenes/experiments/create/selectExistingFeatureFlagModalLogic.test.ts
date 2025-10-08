import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { FeatureFlagModalFilters, selectExistingFeatureFlagModalLogic } from './selectExistingFeatureFlagModalLogic'

describe('selectExistingFeatureFlagModalLogic', () => {
    let logic: ReturnType<typeof selectExistingFeatureFlagModalLogic.build>

    const mockFeatureFlags: FeatureFlagType[] = [
        {
            id: 1,
            key: 'test-flag-1',
            name: 'Test Flag 1',
            filters: {
                groups: [],
                payloads: {},
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            },
            created_at: '2021-01-01',
            updated_at: '2021-01-01',
            created_by: null,
            is_simple_flag: false,
            is_remote_configuration: false,
            deleted: false,
            active: true,
            rollout_percentage: null,
            experiment_set: null,
            features: null,
            surveys: null,
            rollback_conditions: [],
            performed_rollback: false,
            can_edit: true,
            tags: [],
            ensure_experience_continuity: null,
            user_access_level: AccessControlLevel.Admin,
            status: 'ACTIVE',
            has_encrypted_payloads: false,
            version: 0,
            last_modified_by: null,
            evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
            evaluation_tags: [],
        },
        {
            id: 2,
            key: 'test-flag-2',
            name: 'Test Flag 2',
            filters: {
                groups: [],
                payloads: {},
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'variant-1', rollout_percentage: 33 },
                        { key: 'variant-2', rollout_percentage: 34 },
                    ],
                },
            },
            created_at: '2021-01-02',
            updated_at: '2021-01-02',
            created_by: null,
            is_simple_flag: false,
            is_remote_configuration: false,
            deleted: false,
            active: true,
            rollout_percentage: null,
            experiment_set: null,
            features: null,
            surveys: null,
            rollback_conditions: [],
            performed_rollback: false,
            can_edit: true,
            tags: [],
            ensure_experience_continuity: null,
            user_access_level: AccessControlLevel.Admin,
            status: 'ACTIVE',
            has_encrypted_payloads: false,
            version: 0,
            last_modified_by: null,
            evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
            evaluation_tags: [],
        },
    ]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/feature_flags/': (req) => {
                    const url = new URL(req.url, 'http://localhost')
                    const search = url.searchParams.get('search')

                    const filteredFlags = search
                        ? mockFeatureFlags.filter((flag) => flag.key.toLowerCase().includes(search.toLowerCase()))
                        : mockFeatureFlags

                    return [
                        200,
                        {
                            results: filteredFlags,
                            count: filteredFlags.length,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = selectExistingFeatureFlagModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('modal state', () => {
        it('starts with modal closed', async () => {
            await expectLogic(logic).toMatchValues({
                isModalOpen: false,
            })
        })

        it('opens modal when openSelectExistingFeatureFlagModal is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSelectExistingFeatureFlagModal()
            })
                .toDispatchActions(['openSelectExistingFeatureFlagModal'])
                .toMatchValues({
                    isModalOpen: true,
                })
        })

        it('closes modal when closeSelectExistingFeatureFlagModal is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSelectExistingFeatureFlagModal()
                logic.actions.closeSelectExistingFeatureFlagModal()
            })
                .toDispatchActions(['openSelectExistingFeatureFlagModal', 'closeSelectExistingFeatureFlagModal'])
                .toMatchValues({
                    isModalOpen: false,
                })
        })

        it('loads feature flags when modal is opened', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSelectExistingFeatureFlagModal()
            }).toDispatchActions(['openSelectExistingFeatureFlagModal', 'loadFeatureFlags', 'loadFeatureFlagsSuccess'])
        })
    })

    describe('filters management', () => {
        it('starts with default filters', async () => {
            await expectLogic(logic).toMatchValues({
                filters: {
                    active: undefined,
                    created_by_id: undefined,
                    search: undefined,
                    order: undefined,
                    page: 1,
                    evaluation_runtime: undefined,
                },
            })
        })

        it('merges filters when setFilters is called without replace', async () => {
            const newFilters: Partial<FeatureFlagModalFilters> = {
                search: 'test',
                page: 2,
            }

            await expectLogic(logic, () => {
                logic.actions.setFilters(newFilters)
            })
                .toDispatchActions(['setFilters'])
                .toMatchValues({
                    filters: {
                        active: undefined,
                        created_by_id: undefined,
                        search: 'test',
                        order: undefined,
                        page: 2,
                        evaluation_runtime: undefined,
                    },
                })
        })

        it('replaces filters when setFilters is called with replace=true', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'first', page: 3 })
                logic.actions.setFilters({ page: 1 }, true)
            })
                .toDispatchActions(['setFilters', 'setFilters'])
                .toMatchValues({
                    filters: {
                        active: undefined,
                        created_by_id: undefined,
                        search: undefined,
                        order: undefined,
                        page: 1,
                        evaluation_runtime: undefined,
                    },
                })
        })

        it('resets filters to default when resetFilters is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'test', page: 5, active: 'true' })
                logic.actions.resetFilters()
            })
                .toDispatchActions(['setFilters', 'resetFilters'])
                .toMatchValues({
                    filters: {
                        active: undefined,
                        created_by_id: undefined,
                        search: undefined,
                        order: undefined,
                        page: 1,
                        evaluation_runtime: undefined,
                    },
                })
        })

        it('loads feature flags after filter reset', async () => {
            await expectLogic(logic, () => {
                logic.actions.resetFilters()
            }).toDispatchActions(['resetFilters', 'loadFeatureFlags'])
        })

        it('debounces and loads feature flags after setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'test' })
            })
                .delay(350)
                .toDispatchActions(['setFilters', 'loadFeatureFlags'])
        })
    })

    describe('feature flags loading', () => {
        it('loads feature flags successfully', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadFeatureFlags()
            })
                .toDispatchActions(['loadFeatureFlags', 'loadFeatureFlagsSuccess'])
                .toMatchValues({
                    featureFlags: {
                        results: mockFeatureFlags,
                        count: mockFeatureFlags.length,
                    },
                })
        })

        it('filters feature flags by search term', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'flag-1' })
            })
                .delay(350)
                .toDispatchActions(['setFilters', 'loadFeatureFlags', 'loadFeatureFlagsSuccess'])
                .toMatchValues({
                    featureFlags: {
                        results: [mockFeatureFlags[0]],
                        count: 1,
                    },
                })
        })
    })

    describe('pagination', () => {
        it('calculates pagination correctly when no results', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [
                        200,
                        {
                            results: [],
                            count: 0,
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadFeatureFlags()
            })
                .toDispatchActions(['loadFeatureFlagsSuccess'])
                .toMatchValues({
                    pagination: {
                        controlled: true,
                        pageSize: 100,
                        currentPage: 1,
                        entryCount: 0,
                        onForward: undefined,
                        onBackward: undefined,
                    },
                })
        })

        it('disables forward/backward when only one page', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadFeatureFlags()
            })
                .toDispatchActions(['loadFeatureFlagsSuccess'])
                .toMatchValues({
                    pagination: {
                        controlled: true,
                        pageSize: 100,
                        currentPage: 1,
                        entryCount: 2,
                        onForward: undefined,
                        onBackward: undefined,
                    },
                })
        })

        it('enables forward button when there are more pages', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [
                        200,
                        {
                            results: mockFeatureFlags,
                            count: 125,
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadFeatureFlags()
            })
                .toDispatchActions(['loadFeatureFlagsSuccess'])
                .toMatchValues({
                    pagination: {
                        controlled: true,
                        pageSize: 100,
                        currentPage: 1,
                        entryCount: 125,
                        onForward: expect.any(Function),
                        onBackward: undefined,
                    },
                })
        })

        it('enables backward button when on page 2+', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [
                        200,
                        {
                            results: mockFeatureFlags,
                            count: 125,
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ page: 2 })
            })
                .delay(350)
                .toMatchValues({
                    pagination: {
                        controlled: true,
                        pageSize: 100,
                        currentPage: 2,
                        entryCount: 125,
                        onForward: undefined,
                        onBackward: expect.any(Function),
                    },
                })
        })

        it('updates page when onForward is called', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [
                        200,
                        {
                            results: mockFeatureFlags,
                            count: 125,
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadFeatureFlags()
            }).toDispatchActions(['loadFeatureFlagsSuccess'])

            const { pagination } = logic.values

            await expectLogic(logic, () => {
                pagination.onForward?.()
            })
                .delay(350)
                .toMatchValues({
                    filters: expect.objectContaining({
                        page: 2,
                    }),
                })
        })

        it('updates page when onBackward is called', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [
                        200,
                        {
                            results: mockFeatureFlags,
                            count: 125,
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ page: 3 })
            })
                .delay(350)
                .toDispatchActions(['loadFeatureFlagsSuccess'])

            const { pagination } = logic.values

            await expectLogic(logic, () => {
                pagination.onBackward?.()
            })
                .delay(350)
                .toMatchValues({
                    filters: expect.objectContaining({
                        page: 2,
                    }),
                })
        })

        it('never goes below page 1 when onBackward is called', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [
                        200,
                        {
                            results: mockFeatureFlags,
                            count: 125,
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ page: 1 })
            })
                .delay(350)
                .toDispatchActions(['loadFeatureFlagsSuccess'])

            const { pagination } = logic.values
            expect(pagination.onBackward).toBeUndefined()
        })
    })

    describe('paramsFromFilters selector', () => {
        it('converts filters to API params with limit and offset', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({
                    search: 'test',
                    active: 'true',
                    page: 2,
                })
            }).toMatchValues({
                paramsFromFilters: {
                    search: 'test',
                    active: 'true',
                    page: 2,
                    limit: 100,
                    offset: 100,
                    created_by_id: undefined,
                    order: undefined,
                    evaluation_runtime: undefined,
                },
            })
        })

        it('calculates correct offset for different pages', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ page: 1 })
            }).toMatchValues({
                paramsFromFilters: expect.objectContaining({
                    offset: 0,
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ page: 3 })
            }).toMatchValues({
                paramsFromFilters: expect.objectContaining({
                    offset: 200,
                }),
            })
        })
    })
})
