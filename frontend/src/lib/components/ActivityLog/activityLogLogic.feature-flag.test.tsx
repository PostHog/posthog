import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityScope,
    Describer,
    PersonMerge,
} from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import React from 'react'
import { MOCK_TEAM_ID } from 'lib/api.mock'

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('humanzing', () => {
        interface APIMockSetup {
            name: string
            activity: string
            changes?: ActivityChange[] | null
            scope: ActivityScope
            merge?: PersonMerge | null
        }

        const makeAPIItem = ({
            name,
            activity,
            changes = null,
            scope,
            merge = null,
        }: APIMockSetup): ActivityLogItem => ({
            user: { first_name: 'peter', email: 'peter@posthog.com' },
            activity,
            scope,
            item_id: '7',
            detail: {
                changes,
                merge,
                name,
            },
            created_at: '2022-02-05T16:28:39.594Z',
        })

        async function testSetup(
            activityLogItem: ActivityLogItem,
            scope: ActivityScope,
            describer: Describer,
            url: string
        ): Promise<void> {
            useMocks({
                get: {
                    [url]: {
                        results: [activityLogItem],
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope, id: 7, describer })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
        }

        const makeTestSetup = (scope: ActivityScope, describer: Describer, url: string) => {
            return async (name: string, activity: string, changes: ActivityChange[] | null, merge?: PersonMerge) => {
                await testSetup(makeAPIItem({ scope, name, activity, changes, merge }), scope, describer, url)
            }
        }

        describe('humanizing feature flags', () => {
            const featureFlagsTestSetup = makeTestSetup(
                ActivityScope.FEATURE_FLAG,
                flagActivityDescriber,
                `/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`
            )

            it('can handle change of key', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'key',
                        before: 'the-first-key',
                        after: 'the-second-key',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed flag key on the-first-key to the-second-key'
                )
            })

            it('can handle soft deletion', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'deleted',
                        after: 'true',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter deleted test flag')
            })

            it('can handle soft un-deletion', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'deleted',
                        after: 'false',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter un-deleted test flag')
            })

            it('can handle soft enabling flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'active',
                        after: 'true',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter enabled test flag')
            })

            it('can handle soft disabling flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'active',
                        after: 'false',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter disabled test flag')
            })

            it('can handle enabling experience continuity for a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'ensure_experience_continuity',
                        after: 'true',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter enabled experience continuity on test flag'
                )
            })

            it('can handle disabling experience continuity for a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'ensure_experience_continuity',
                        after: 'false',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter disabled experience continuity on test flag'
                )
            })

            it('can handle deleting several groups from a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        before: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                                {
                                    properties: [],
                                    rollout_percentage: 40,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0]?.description}</>).container).toHaveTextContent(
                    'peter removed 2 release conditions on test flag'
                )
            })

            it('can handle deleting a group from a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        before: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0]?.description}</>).container).toHaveTextContent(
                    'peter removed 1 release condition on test flag'
                )
            })

            it('can handle rollout percentage change', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'rollout_percentage',
                        after: '36',
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed rollout percentage to 36% on test flag'
                )
            })

            it('can handle deleting the first of several groups from a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        before: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0]?.description}</>).container).toHaveTextContent(
                    'peter changed the filter conditions to apply to 30% of all users, and removed 1 release condition on test flag'
                )
            })

            it('can humanize more than one change', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'rollout_percentage',
                        after: '36',
                    },
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'name',
                        after: 'strawberry',
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed rollout percentage to 36%, and changed the description on test flag'
                )
            })

            it('can handle filter change - boolean value, no conditions', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        after: { groups: [{ properties: [], rollout_percentage: 99 }], multivariate: null },
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed the filter conditions to apply to 99% of all users on test flag'
                )
            })

            it('can handle filter change with cohort', async () => {
                await featureFlagsTestSetup('with cohort', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        after: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 411,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: 100,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed the filter conditions to apply to 100% ofID 98, and 100% ofID 411 on with cohort'
                )
            })

            it('can describe a simple rollout percentage change', async () => {
                await featureFlagsTestSetup('with simple rollout change', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        before: {
                            groups: [
                                {
                                    properties: [],
                                    rollout_percentage: 75,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [],
                                    rollout_percentage: 77,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed the filter conditions to apply to 77% of all users on with simple rollout change'
                )
            })

            it('describes a null rollout percentage as 100%', async () => {
                await featureFlagsTestSetup('with null rollout change', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        before: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            value: 98,
                                            operator: null,
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                                {
                                    properties: [
                                        {
                                            key: 'email',
                                            type: 'person',
                                            value: 'someone@somewhere.dev',
                                            operator: 'exact',
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed the filter conditions to apply to 100% ofemail = someone@somewhere.dev on with null rollout change'
                )
            })

            it('can describe two property changes', async () => {
                await featureFlagsTestSetup('with two changes', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        before: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: '$initial_browser',
                                            type: 'person',
                                            value: ['Chrome'],
                                            operator: 'exact',
                                        },
                                    ],
                                    rollout_percentage: 77,
                                },
                                {
                                    properties: [
                                        {
                                            key: '$initial_browser_version',
                                            type: 'person',
                                            value: ['100'],
                                            operator: 'exact',
                                        },
                                    ],
                                    rollout_percentage: null,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [
                                        {
                                            key: '$initial_browser',
                                            type: 'person',
                                            value: ['Chrome'],
                                            operator: 'exact',
                                        },
                                    ],
                                    rollout_percentage: 76,
                                },
                                {
                                    properties: [
                                        {
                                            key: '$initial_browser_version',
                                            type: 'person',
                                            value: ['100'],
                                            operator: 'exact',
                                        },
                                    ],
                                    rollout_percentage: 99,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter changed the filter conditions to apply to 76% ofInitial Browser = Chrome , and 99% ofInitial Browser Version = 100 on with two changes'
                )
            })
        })
    })
})
