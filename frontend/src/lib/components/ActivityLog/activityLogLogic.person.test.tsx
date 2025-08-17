import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'
import { render } from '@testing-library/react'

import { makeTestSetup } from 'lib/components/ActivityLog/activityLogLogic.test.setup'

import { ActivityScope } from '~/types'

describe('the activity log logic', () => {
    describe('humanizing persons', () => {
        const personTestSetup = makeTestSetup(
            ActivityScope.PERSON,
            `/api/environments/${MOCK_TEAM_ID}/persons/7/activity/`
        )
        it('can handle addition of a property', async () => {
            const logic = await personTestSetup('test person', 'updated', [
                {
                    type: ActivityScope.PERSON,
                    action: 'changed',
                    field: 'properties',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent("edited this person's properties")
        })

        it('can handle merging people', async () => {
            const logic = await personTestSetup('test person', 'people_merged_into', null, {
                type: ActivityScope.PERSON,
                source: [
                    { distinct_ids: ['a'], properties: {} },
                    { distinct_ids: ['c'], properties: {} },
                ],
                target: { distinct_ids: ['d'], properties: {} },
            })
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter merged a, and c into this person'
            )
        })

        it('can handle splitting people', async () => {
            const logic = await personTestSetup('test_person', 'split_person', [
                {
                    type: ActivityScope.PERSON,
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
