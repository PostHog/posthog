import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    FeatureFlagGroupType,
    FeatureFlagType,
    FlagPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { FeatureFlagReleaseConditionsReadonly } from './FeatureFlagReleaseConditionsReadonly'

const flagDependencyFilter: FlagPropertyFilter = {
    type: PropertyFilterType.Flag,
    key: '42',
    operator: PropertyOperator.FlagEvaluatesTo,
    value: true,
}

function buildFilters(): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties: [flagDependencyFilter],
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return { groups: [group], multivariate: null, payloads: {} }
}

describe('feature flag release conditions flag dependency label', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            post: {
                '/api/projects/:team/feature_flags/bulk_keys/': [200, { keys: { '42': 'beta-banner' } }],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the resolved flag key, not the raw ID, in the readonly condition card', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsReadonly id="1234" filters={buildFilters()} />
            </Provider>
        )

        await waitFor(() => {
            expect(document.body).toHaveTextContent('beta-banner')
        })
        expect(document.body.textContent).not.toMatch(/\b42\b/)
    })

    it('shows the resolved flag key, not the raw ID, in the collapsed condition summary', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsCollapsible id="1234" filters={buildFilters()} readOnly />
            </Provider>
        )

        await waitFor(() => {
            expect(document.body).toHaveTextContent('beta-banner')
        })
        expect(document.body.textContent).not.toMatch(/\b42\b/)
    })
})
