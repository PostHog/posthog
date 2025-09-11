import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'
import { expectLogic } from 'kea-test-utils'

import { featureFlagsActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { activityLogLogic, describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/feature_flags/activity/`]: {
                        results: featureFlagsActivityResponseJson,
                        next: 'a provided url',
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.FEATURE_FLAG })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/all')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchActivity', 'fetchActivitySuccess'])
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                activityLoading: false,
            })

            // react fragments confuse equality check so,
            // stringify to confirm this value has the humanized version of the response
            // detailed tests for humanization are below
            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, describerFor))
            )
        })
    })

    describe('when scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`]: {
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
            await expectLogic(logic).toDispatchActions(['fetchActivity', 'fetchActivitySuccess'])
        })
    })

    describe('when starting at page 4', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`]: (req) => {
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
            await expectLogic(logic).toDispatchActions(['fetchActivity', 'fetchActivitySuccess'])

            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, describerFor))
            )
        })
    })

    describe('incident regression test for #inc-2023-03-09-us-cloud-ui-unavailable-when-users-have-a-notification', () => {
        it('backend sends unexpected field and describer should not explode', () => {
            expect(() => {
                humanize(
                    [
                        {
                            // a very unexpected activity log item received in production
                            type: 'insight',
                            after: true,
                            field: 'saved',
                            action: 'changed',
                            before: false,
                        } as unknown as ActivityLogItem,
                    ],
                    describerFor,
                    true
                )
            }).not.toThrow()
        })
    })
})
