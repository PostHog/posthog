import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import {
    CohortPropertyFilter,
    CohortType,
    FeatureFlagGroupType,
    FilterLogicalOperator,
    FeatureFlagFilters,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const cohortPowerUsers: Partial<CohortType> = {
    id: 1,
    name: 'Power Users',
    filters: { properties: { id: 'root', type: FilterLogicalOperator.Or, values: [] } },
}

const cohortFilter: CohortPropertyFilter = {
    type: PropertyFilterType.Cohort,
    key: 'id',
    value: 1,
    operator: PropertyOperator.NotIn,
    cohort_name: 'Power Users',
}

function buildFilters(property: CohortPropertyFilter = cohortFilter): FeatureFlagFilters {
    const group: FeatureFlagGroupType = {
        properties: [property],
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return { groups: [group], multivariate: null, payloads: {} }
}

describe('feature flag release conditions cohort operator', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/cohorts/': { results: [cohortPowerUsers], next: null, count: 1 },
                // featureFlagLogic mounts alongside and loads the flag; the unhandled-request
                // floor has no `filters`, which crashes payload conversion
                '/api/projects/:team/feature_flags/1234/': {
                    id: 1234,
                    key: 'test-flag',
                    filters: { groups: [], multivariate: null, payloads: {} },
                },
                '/api/projects/:team/actions': { results: [] },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 0, total: 2 }],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the in/not-in operator dropdown for a cohort row in FeatureFlagReleaseConditions', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditions id="1234" filters={buildFilters()} onChange={jest.fn()} />
            </Provider>
        )

        await waitFor(() => {
            expect(document.querySelector('[data-attr="taxonomic-operator"]')).toBeInTheDocument()
        })
    })

    it('renders the in/not-in operator dropdown for a cohort row in FeatureFlagReleaseConditionsCollapsible', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsCollapsible
                    id="1234"
                    flagId={1234}
                    filters={buildFilters()}
                    onChange={jest.fn()}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(document.querySelector('[data-attr="taxonomic-operator"]')).toBeInTheDocument()
        })
    })

    it.each([
        { state: 'a deleted cohort', markers: { cohort_deleted: true }, label: 'Power Users (deleted)' },
        {
            state: 'a missing cohort',
            markers: { cohort_deleted: true, cohort_missing: true },
            label: 'Power Users (missing)',
        },
    ])('keeps $state marked when the operator changes', async ({ markers, label }) => {
        const onChange = jest.fn()
        render(
            <Provider>
                <FeatureFlagReleaseConditions
                    id="1234"
                    filters={buildFilters({ ...cohortFilter, ...markers })}
                    onChange={onChange}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText(label)).toBeInTheDocument()
        })
        expect(document.querySelector('[data-attr="property-filter-deleted-cohort-icon"]')).toBeInTheDocument()
        await userEvent.click(document.querySelector('[data-attr="taxonomic-operator"] button')!)
        await userEvent.click(await screen.findByText('user in'))

        await waitFor(() => {
            expect(onChange.mock.lastCall?.[0].groups[0].properties[0]).toMatchObject({
                operator: PropertyOperator.In,
                cohort_name: 'Power Users',
                ...markers,
            })
        })
    })
})
