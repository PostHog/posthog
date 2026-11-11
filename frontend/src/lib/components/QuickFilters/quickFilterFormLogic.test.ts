import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext, QuickFilterType } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { quickFilterFormLogic } from './quickFilterFormLogic'
import { quickFiltersLogic } from './quickFiltersLogic'

const context = QuickFilterContext.ErrorTrackingIssueFilters

describe('quickFilterFormLogic', () => {
    let createdFilterBodies: Record<string, unknown>[]

    beforeEach(() => {
        createdFilterBodies = []
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
                '/api/event/values/': { results: [], refreshing: false },
            },
            post: {
                '/api/environments/:team_id/quick_filters/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    createdFilterBodies.push(body)
                    return [201, { id: 'new-filter', created_at: '2024-01-01', updated_at: '2024-01-01', ...body }]
                },
            },
        })
        initKeaTests()
        quickFiltersLogic({ context }).mount()
    })

    it.each([
        {
            description: 'saves an auto-discovery filter without options',
            type: 'auto-discovery' as QuickFilterType,
            expectedBodies: [{ type: 'auto-discovery', options: [] }],
        },
        {
            description: 'requires option values for a manual filter',
            type: 'manual-options' as QuickFilterType,
            expectedBodies: [],
        },
    ])('$description', async ({ type, expectedBodies }) => {
        const logic = quickFilterFormLogic({ context, filter: null })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setQuickFilterValues({ name: 'Release', propertyName: '$release', type })
            logic.actions.submitQuickFilter()
        }).toFinishAllListeners()

        expect(createdFilterBodies).toEqual(expectedBodies.map((body) => expect.objectContaining(body)))
    })
})
