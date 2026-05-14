import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { COHORTS_IN_ONLY_PICKER_PROPS, FEATURE_FLAG_COHORT_PICKER_PROPS } from 'scenes/feature-flags/cohortPickerProps'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { CohortPropertyFilter, CohortType, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { TaxonomicFilterGroupType } from '../../TaxonomicFilter/types'
import { PropertyFilters } from '../PropertyFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const cohortPowerUsers: Partial<CohortType> = { id: 1, name: 'Power Users' }

describe('TaxonomicPropertyFilter selectingKeyOnly', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/cohorts/': {
                    results: [cohortPowerUsers],
                    next: null,
                    count: 1,
                },
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

    const cohortFilter: CohortPropertyFilter = {
        type: PropertyFilterType.Cohort,
        key: 'id',
        value: 1,
        operator: PropertyOperator.In,
        cohort_name: 'Power Users',
    }

    const eventFilter: EventPropertyFilter = {
        type: PropertyFilterType.Event,
        key: '$browser',
        value: 'Chrome',
        operator: PropertyOperator.Exact,
    }

    function renderWith(props: Partial<React.ComponentProps<typeof PropertyFilters>>): void {
        render(
            <Provider>
                <PropertyFilters
                    pageKey="selecting-key-only-test"
                    propertyFilters={[cohortFilter]}
                    onChange={jest.fn()}
                    disablePopover
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.EventProperties]}
                    {...props}
                />
            </Provider>
        )
    }

    it.each([
        {
            name: 'no extra props renders the operator+value pair for cohort rows',
            extraProps: {},
            expectOperator: true,
        },
        {
            name: 'feature-flag preset renders the operator+value pair so users can pick "not in"',
            extraProps: FEATURE_FLAG_COHORT_PICKER_PROPS,
            expectOperator: true,
        },
        {
            name: 'workflow trigger preset hides the operator+value pair for cohort rows',
            extraProps: COHORTS_IN_ONLY_PICKER_PROPS,
            expectOperator: false,
        },
        {
            name: 'inline selectingKeyOnly={{ Cohorts: true }} also hides it',
            extraProps: { selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true } },
            expectOperator: false,
        },
        {
            name: 'selectingKeyOnly: true (whole picker) also hides it',
            extraProps: { selectingKeyOnly: true },
            expectOperator: false,
        },
    ])('$name', async ({ extraProps, expectOperator }) => {
        renderWith(extraProps)

        // Wait for the cohort row to render.
        await waitFor(() => {
            expect(screen.getByText('Power Users')).toBeInTheDocument()
        })

        const operator = document.querySelector('[data-attr="taxonomic-operator"]')
        const valueSelect = document.querySelector('[data-attr="taxonomic-value-select"]')

        if (expectOperator) {
            expect(operator).toBeInTheDocument()
        } else {
            expect(operator).not.toBeInTheDocument()
            expect(valueSelect).not.toBeInTheDocument()
        }
    })

    it('keeps the operator+value pair on event-property rows even when Cohorts is key-only', async () => {
        // Event-property filter alongside the cohort one — only the cohort should be key-only.
        render(
            <Provider>
                <PropertyFilters
                    pageKey="selecting-key-only-event-test"
                    propertyFilters={[eventFilter]}
                    onChange={jest.fn()}
                    disablePopover
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.EventProperties]}
                    {...COHORTS_IN_ONLY_PICKER_PROPS}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(document.querySelector('[data-attr="taxonomic-operator"]')).toBeInTheDocument()
        })
    })
})
