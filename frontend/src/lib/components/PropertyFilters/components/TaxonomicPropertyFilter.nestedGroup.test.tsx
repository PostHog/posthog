import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FilterLogicalOperator, PropertyFilterType, PropertyGroupFilterValue, PropertyOperator } from '~/types'

import { TaxonomicFilterGroupType } from '../../TaxonomicFilter/types'
import { PropertyFilters } from '../PropertyFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicPropertyFilter nested group rows', () => {
    beforeEach(() => {
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [] },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('labels a group the editor cannot edit instead of drawing an empty add-filter row', () => {
        const nestedGroup: PropertyGroupFilterValue = {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    key: 'id',
                    value: 3,
                    cohort_name: 'Logged in',
                    operator: PropertyOperator.In,
                    type: PropertyFilterType.Cohort,
                },
                { key: '$browser', value: 'Chrome', operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
            ],
        }

        render(
            <Provider>
                <PropertyFilters
                    pageKey="nested-group-test"
                    propertyFilters={[nestedGroup]}
                    onChange={jest.fn()}
                    orFiltering
                    addText="Filter"
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.Cohorts]}
                />
            </Provider>
        )

        expect(screen.getByText(/Logged in/)).toBeInTheDocument()
        expect(screen.getByText(/Chrome/)).toBeInTheDocument()
    })
})
