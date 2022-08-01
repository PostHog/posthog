import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import React from 'react'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { makeTestSetup } from 'lib/components/ActivityLog/activityLogLogic.test.setup'

describe('the activity log logic', () => {
    describe('humanizing persons', () => {
        const personTestSetup = makeTestSetup(ActivityScope.PERSON, personActivityDescriber, '/api/person/7/activity/')
        it('can handle addition of a property', async () => {
            const logic = await personTestSetup('test person', 'updated', [
                {
                    type: 'Person',
                    action: 'changed',
                    field: 'properties',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent("edited this person's properties")
        })

        it('can handle merging people', async () => {
            const logic = await personTestSetup('test person', 'people_merged_into', null, {
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
            const logic = await personTestSetup('test_person', 'split_person', [
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
