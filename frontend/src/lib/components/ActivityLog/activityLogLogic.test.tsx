import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { ActivityScope, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { featureFlagsActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/activity/': {
                        results: featureFlagsActivityResponseJson,
                        next: 'a provided url',
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.FEATURE_FLAG, describer: flagActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/all')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })

        it('increments the page when loading the next page', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchNextPageSuccess({ results: [] })
                logic.actions.fetchNextPageSuccess({ results: [] })
            }).toMatchValues({ page: 3 })
        })

        it('decrements the page when loading the previous page', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchNextPageSuccess({ results: [] })
                logic.actions.fetchNextPageSuccess({ results: [] })
                logic.actions.fetchPreviousPageSuccess({ results: [] })
            }).toMatchValues({ page: 2 })
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                nextPageLoading: false,
                previousPageLoading: false,
                nextPageURL: 'a provided url',
            })

            // react fragments confuse equality check so stringify to confirm this value has the humanized version of the response
            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, flagActivityDescriber))
            )
        })
    })
    describe('when scoped by ID', () => {
        beforeAll(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': {
                        results: featureFlagsActivityResponseJson,
                        next: 'a provided url',
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.FEATURE_FLAG, id: 7, describer: flagActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/7')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })
    })

    describe('when starting at page 4', () => {
        beforeAll(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': (req) => {
                        const isOnPageFour = req.url.searchParams.get('page') === '4'

                        return [
                            200,
                            {
                                results: isOnPageFour ? featureFlagsActivityResponseJson : [],
                                next: 'a provided url',
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({
                scope: ActivityScope.FEATURE_FLAG,
                id: 7,
                describer: flagActivityDescriber,
                startingPage: 4,
            })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/7')
        })

        it('loads data from page 4 on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])

            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, flagActivityDescriber))
            )
        })
    })
})
