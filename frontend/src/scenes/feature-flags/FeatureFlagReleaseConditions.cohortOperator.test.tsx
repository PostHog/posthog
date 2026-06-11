import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import {
    CohortPropertyFilter,
    CohortType,
    FeatureFlagGroupType,
    FilterLogicalOperator,
    FeatureFlagType,
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

function buildFilters(): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties: [cohortFilter],
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
})
