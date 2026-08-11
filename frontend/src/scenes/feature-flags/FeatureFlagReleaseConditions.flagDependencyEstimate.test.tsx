import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    FeatureFlagGroupType,
    FeatureFlagType,
    FlagPropertyFilter,
    PersonPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

const flagDependencyFilter: FlagPropertyFilter = {
    type: PropertyFilterType.Flag,
    key: '42',
    operator: PropertyOperator.FlagEvaluatesTo,
    value: 'variant',
}
const personFilter: PersonPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.Exact,
    value: ['someone@example.com'],
}

function buildFilters(properties: FeatureFlagGroupType['properties']): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties,
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return { groups: [group], multivariate: null, payloads: {} }
}

describe('feature flag release conditions flag dependency estimate', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            post: {
                '/api/projects/:team/feature_flags/bulk_keys/': [200, { keys: { '42': 'beta-banner' } }],
                // The estimate ignores flag dependencies and would otherwise report the whole person base.
                '/api/projects/:team/feature_flags/user_blast_radius': [200, { affected: 500000, total: 500000 }],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('hides the misleading count when the only filter is a flag dependency', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsCollapsible id="1234" filters={buildFilters([flagDependencyFilter])} />
            </Provider>
        )

        await waitFor(() => {
            expect(document.body).toHaveTextContent('Depends on another feature flag')
        })
        expect(document.body.textContent).not.toContain('500,000')
    })

    it('marks the count as an upper bound when a flag dependency is mixed with other filters', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsCollapsible
                    id="1234"
                    filters={buildFilters([flagDependencyFilter, personFilter])}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(document.body).toHaveTextContent('at most')
        })
    })
})
