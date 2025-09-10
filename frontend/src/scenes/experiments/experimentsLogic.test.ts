import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { experimentsLogic } from './experimentsLogic'

describe('experimentsLogic', () => {
    let logic: ReturnType<typeof experimentsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'get')
        api.get.mockClear()
        logic = experimentsLogic()
        logic.mount()
    })

    describe('feature flag modal filters', () => {
        it('loads feature flags on mount', async () => {
            await expectLogic(logic).toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/api\/projects\/\d+\/feature_flags\/\?/))
        })

        it('updates filters and triggers new API call', async () => {
            api.get.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagModalFilters({ search: 'test', page: 1 })
            })
                .toMatchValues({
                    featureFlagModalFilters: expect.objectContaining({
                        search: 'test',
                        page: 1,
                    }),
                })
                .delay(350) // Wait for debounce
                .toFinishAllListeners()

            expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=test'))
        })

        it('resets filters to defaults', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagModalFilters({ search: 'test' })
                logic.actions.resetFeatureFlagModalFilters()
            }).toMatchValues({
                featureFlagModalFilters: {
                    active: undefined,
                    created_by_id: undefined,
                    type: undefined,
                    search: undefined,
                    order: undefined,
                    page: 1,
                    evaluation_runtime: undefined,
                },
            })
        })

        it('constructs API params correctly', async () => {
            logic.actions.setFeatureFlagModalFilters({
                search: 'test',
                type: 'boolean',
                active: 'true',
                page: 2,
            })

            await expectLogic(logic).toMatchValues({
                featureFlagModalParamsFromFilters: {
                    search: 'test',
                    type: 'boolean',
                    active: 'true',
                    page: 2,
                    limit: 100,
                    offset: 100,
                },
            })
        })
    })
})
