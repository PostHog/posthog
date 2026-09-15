import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { ActivityScope } from '~/types'

import { makeTestSetup } from './activityLogLogic.test.setup'

describe('the activity log logic', () => {
    describe('humanizing feature flags', () => {
        const featureFlagsTestSetup = makeTestSetup(
            ActivityScope.FEATURE_FLAG,
            `/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`
        )

        it('drops an entry whose only change is the version bump', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'version',
                    before: 1,
                    after: 2,
                },
            ])

            expect(logic.values.humanizedActivity).toHaveLength(0)
        })

        it('keeps the generic row for a describable change the handler cannot narrate', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: { groups: [{ properties: [], rollout_percentage: 50 }] },
                    after: {},
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(actual).toHaveLength(1)
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter updated')
        })

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

        it('can handle soft restoration', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'deleted',
                    after: 'false',
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter restored test flag')
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
                'peter removed 2 condition sets on test flag'
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
                'peter removed the condition set for all users on test flag'
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
                'peter removed the condition set for User in ID 98 on test flag'
            )
        })

        it('can humanize more than one change', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'active',
                    after: 'true',
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
                'peter enabled, and changed the description test flag'
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
                'peter added a condition set for all users at 99% on test flag'
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
                'peter added condition sets for User in ID 98 at 100% and User not in ID 411 at 100% on with cohort'
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
                'peter changed the rollout for all users from 75% to 77% on with simple rollout change'
            )
            expect(actual[0].expandedView?.label).toEqual('Release conditions')
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
                'peter added a condition set for Email address = …@somewhere.dev at 100% on with null rollout change'
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
                'peter changed the rollout for Initial browser = Chrome from 77% to 76% and Initial browser version = 100 from 100% to 99% on with two changes'
            )
        })

        it.each([
            {
                name: 'lists every set at the detail limit',
                initials: ['a', 'b', 'c'],
                expected:
                    'peter changed the rollout for Email address = a@example.com from 50% to 100%, Email address = b@example.com from 50% to 100% and Email address = c@example.com from 50% to 100% on test flag',
            },
            {
                name: 'lists counts instead of every set past the detail limit',
                initials: ['a', 'b', 'c', 'd'],
                expected: 'peter changed the rollout for 4 condition sets on test flag',
            },
        ])('$name', async ({ initials, expected }) => {
            const emailSet = (email: string, rollout: number): Record<string, unknown> => ({
                properties: [{ key: 'email', type: 'person', value: [email], operator: 'exact' }],
                rollout_percentage: rollout,
            })
            const emails = initials.map((initial) => `${initial}@example.com`)
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: { groups: emails.map((email) => emailSet(email, 50)), multivariate: null },
                    after: { groups: emails.map((email) => emailSet(email, 100)), multivariate: null },
                },
            ])

            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(expected)
        })

        it('counts condition sets whose description changed past the detail limit', async () => {
            const describedSet = (initial: string, description: string): Record<string, unknown> => ({
                properties: [{ key: 'email', type: 'person', value: [`${initial}@example.com`], operator: 'exact' }],
                rollout_percentage: 50,
                description,
            })
            const initials = ['a', 'b', 'c', 'd']
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: { groups: initials.map((initial) => describedSet(initial, 'before')), multivariate: null },
                    after: { groups: initials.map((initial) => describedSet(initial, 'after')), multivariate: null },
                },
            ])

            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter changed the description of 4 condition sets on test flag'
            )
        })

        it('names a set once when its criteria and rollout both change', async () => {
            const emailSet = (email: string, rollout: number): Record<string, unknown> => ({
                properties: [{ key: 'email', type: 'person', value: [email], operator: 'exact' }],
                rollout_percentage: rollout,
            })
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: { groups: [emailSet('a@example.com', 75)], multivariate: null },
                    after: { groups: [emailSet('b@example.com', 100)], multivariate: null },
                },
            ])

            const container = render(<>{logic.values.humanizedActivity[0].description}</>).container

            expect(container).toHaveTextContent(
                'peter changed the criteria for Email address = b@example.com and its rollout from 75% to 100% on test flag'
            )
            expect(container.textContent?.match(/Email address = b@example\.com/g)).toHaveLength(1)
        })

        it('names the variant a condition set moved to without mentioning variant rollout', async () => {
            const multivariate = {
                variants: [
                    { key: 'control', rollout_percentage: 100 },
                    { key: 'variant', rollout_percentage: 0 },
                ],
            }
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [{ variant: null, properties: [], rollout_percentage: 20 }],
                        payloads: {},
                        multivariate,
                    },
                    after: {
                        groups: [{ variant: 'variant', properties: [], rollout_percentage: 20 }],
                        payloads: {},
                        multivariate,
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            const container = render(<>{actual[0].description}</>).container
            expect(container).toHaveTextContent(
                'peter changed the variant for all users from none to variant on test flag'
            )
            expect(container.textContent).not.toContain('changed the rollout percentage for the variants')
        })

        it('only lists variants whose rollout percentage actually changed', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [{ properties: [], rollout_percentage: 75 }],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test-1', rollout_percentage: 25 },
                                { key: 'test-2', rollout_percentage: 25 },
                            ],
                        },
                    },
                    after: {
                        groups: [{ properties: [], rollout_percentage: 75 }],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test-1', rollout_percentage: 40 },
                                { key: 'test-2', rollout_percentage: 10 },
                            ],
                        },
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            const text = render(<>{actual[0].description}</>).container.textContent
            expect(text).toContain('test-1: 40%')
            expect(text).toContain('test-2: 10%')
            expect(text).not.toContain('control: 50%')
        })

        it.each([
            {
                name: 'multivariate flag',
                payloads: { control: 'old-payload' },
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            },
            {
                name: 'boolean flag',
                payloads: { true: 'my-payload' },
                multivariate: null,
            },
        ])('does not mention payload change when payload is unchanged on $name', async ({ payloads, multivariate }) => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: { groups: [{ properties: [], rollout_percentage: 50 }], payloads, multivariate },
                    after: { groups: [{ properties: [], rollout_percentage: 80 }], payloads, multivariate },
                },
            ])

            const text = render(<>{logic.values.humanizedActivity[0].description}</>).container.textContent
            expect(text).not.toContain('changed payload')
        })

        it('offers no release conditions view when only a variant payload changed', async () => {
            const groups = [{ properties: [], rollout_percentage: 50 }]
            const multivariate = {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            }
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: { groups, payloads: { control: 'old' }, multivariate },
                    after: { groups, payloads: { control: 'new' }, multivariate },
                },
            ])

            const actual = logic.values.humanizedActivity
            const text = render(<>{actual[0].description}</>).container.textContent ?? ''
            expect(text.match(/changed payload/g)).toHaveLength(1)
            expect(text).toContain('variant: control')
            expect(actual[0].expandedView).toBeUndefined()
        })

        it('can handle changing variants from a multivariate flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
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
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test-1', rollout_percentage: 50 },
                            ],
                        },
                    },
                    after: {
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 75,
                            },
                        ],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 60 },
                                { key: 'test-1', rollout_percentage: 40 },
                            ],
                        },
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter changed the rollout percentage for the variants to control: 60%, and test-1: 40% on test flag'
            )
        })

        it('can handle removing variant from a multivariate flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
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
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 33 },
                                { key: 'test-1', rollout_percentage: 33 },
                                { key: 'test-2', rollout_percentage: 34 },
                            ],
                        },
                    },
                    after: {
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 75,
                            },
                        ],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test-1', rollout_percentage: 50 },
                            ],
                        },
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter changed the rollout percentage for the variants to control: 50%, and test-1: 50%, and removed variant test-2 on test flag'
            )
        })

        it('can handle removing more than one variant from a multivariate flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
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
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 33 },
                                { key: 'test-1', rollout_percentage: 33 },
                                { key: 'test-2', rollout_percentage: 34 },
                                { key: 'test-3', rollout_percentage: 34 },
                            ],
                        },
                    },
                    after: {
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 75,
                            },
                        ],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test-1', rollout_percentage: 50 },
                            ],
                        },
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter changed the rollout percentage for the variants to control: 50%, and test-1: 50%, and removed variants test-2, and test-3 on test flag'
            )
        })

        it.each([
            {
                name: 'null multivariate',
                after: { multivariate: null },
            },
            {
                name: 'empty variants array',
                after: { multivariate: { variants: [] } },
            },
            {
                name: 'undefined multivariate',
                after: { multivariate: undefined },
            },
        ])('can handle removing all variants when $name', async ({ after }) => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
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
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 33 },
                                { key: 'test-1', rollout_percentage: 33 },
                            ],
                        },
                    },
                    after: {
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 75,
                            },
                        ],
                        ...after,
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter removed all variants on test flag'
            )
        })

        it('describes the payload change when the same save removes all variants', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
                {
                    type: ActivityScope.FEATURE_FLAG,
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [{ properties: [], rollout_percentage: 75 }],
                        payloads: { control: 'a' },
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 50 },
                                { key: 'test-1', rollout_percentage: 50 },
                            ],
                        },
                    },
                    after: {
                        groups: [{ properties: [], rollout_percentage: 75 }],
                        payloads: { true: 'b' },
                        multivariate: { variants: [] },
                    },
                },
            ])

            const container = render(<>{logic.values.humanizedActivity[0].description}</>).container

            expect(container).toHaveTextContent('changed payload to b')
            expect(container).toHaveTextContent('removed all variants')
        })

        it('can handle removing the last variant from a multivariate flag', async () => {
            const logic = await featureFlagsTestSetup('test flag', 'updated', [
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
                        multivariate: {
                            variants: [{ key: 'control', rollout_percentage: 100 }],
                        },
                    },
                    after: {
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 75,
                            },
                        ],
                        multivariate: null,
                    },
                },
            ])

            const actual = logic.values.humanizedActivity
            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter removed the last variant on test flag'
            )
        })
    })
})
