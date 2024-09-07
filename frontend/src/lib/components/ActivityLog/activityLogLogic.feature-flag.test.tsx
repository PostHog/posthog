import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { MOCK_TEAM_ID } from 'lib/api.mock'

import { ActivityScope } from '~/types'

import { makeTestSetup } from './activityLogLogic.test.setup'

describe('the activity log logic', () => {
    describe('humanizing feature flags', () => {
        const featureFlagsTestSetup = makeTestSetup(
            ActivityScope.FEATURE_FLAG,
            `/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`
        )

        it('can handle change of key', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'deleted',
                    after: 'true',
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter deleted test flag')
        })

        it('can handle soft un-deletion', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'deleted',
                    after: 'false',
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter un-deleted test flag')
        })

        it('can handle soft enabling flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'active',
                    after: 'true',
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter enabled test flag')
        })

        it('can handle soft disabling flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'active',
                    after: 'false',
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter disabled test flag')
        })

        it('can handle enabling experience continuity for a flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'rollout_percentage',
                    after: '36',
                },
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('with cohort', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
                                        operator: 'in',
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
                                        operator: 'not_in',
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
                'peter changed the filter conditions to apply to 100% of ID 98 contains person, and 100% of ID 411 does not contain person on with cohort'
            )
        })

        it('can describe a simple rollout percentage change', async () => {
            const logic = await featureFlagsTestSetup('with simple rollout change', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
            const logic = await featureFlagsTestSetup('with null rollout change', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
                'peter changed the filter conditions to apply to 100% of email = someone@somewhere.dev on with null rollout change'
            )
        })

        it('can describe two property changes', async () => {
            const logic = await featureFlagsTestSetup('with two changes', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
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
                'peter changed the filter conditions to apply to 76% of Initial Browser = Chrome , and 99% of Initial Browser Version = 100 on with two changes'
            )
        })
    })
})
