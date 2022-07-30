import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityScope,
    Describer,
    humanize,
    PersonMerge,
} from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { personActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import React from 'react'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when scoped to person', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/person/7/activity': { results: personActivityResponseJson },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.PERSON, id: 7, describer: personActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/Person/7')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])

            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(personActivityResponseJson, personActivityDescriber))
            )
        })
    })

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

        describe('humanizing persons', () => {
            const personTestSetup = makeTestSetup(
                ActivityScope.PERSON,
                personActivityDescriber,
                '/api/person/7/activity/'
            )
            it('can handle addition of a property', async () => {
                await personTestSetup('test person', 'updated', [
                    {
                        type: 'Person',
                        action: 'changed',
                        field: 'properties',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    "edited this person's properties"
                )
            })

            it('can handle merging people', async () => {
                await personTestSetup('test person', 'people_merged_into', null, {
                    type: 'Person',
                    source: [
                        { distinct_ids: ['a'], properties: {} },
                        { distinct_ids: ['c'], properties: {} },
                    ],
                    target: { distinct_ids: ['d'], properties: {} },
                })
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter merged User A, and User C into this person'
                )
            })

            it('can handle splitting people', async () => {
                await personTestSetup('test_person', 'split_person', [
                    {
                        type: 'Person',
                        action: 'changed',
                        field: undefined,
                        before: {},
                        after: { distinct_ids: ['a', 'b'] },
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'peter split this person into a, and b'
                )
            })
        })
    })
})
