import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagGroupType, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

function buildFilters(): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties: [
            {
                key: 'aloha',
                value: 'aloha',
                type: PropertyFilterType.Person,
                operator: PropertyOperator.Exact,
            },
        ],
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return { groups: [group], multivariate: null, payloads: {} }
}

describe('feature flag release conditions blast radius error', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': { results: [] },
                '/api/projects/:team/property_definitions': { results: [] },
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
                // A deterministic 400 must not offer a Retry that would just fail again.
                '/api/projects/:team/feature_flags/user_blast_radius': () => [
                    400,
                    { detail: 'These filters are invalid.' },
                ],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('hides Retry and shows the backend detail in FeatureFlagReleaseConditions', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditions id="1234" filters={buildFilters()} onChange={jest.fn()} />
            </Provider>
        )

        await waitFor(() => {
            expect(document.body).toHaveTextContent('These filters are invalid.')
        })
        expect(document.body).not.toHaveTextContent('Retry')
    })

    it('hides Retry and shows the backend detail in FeatureFlagReleaseConditionsCollapsible', async () => {
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
            expect(document.body).toHaveTextContent('These filters are invalid.')
        })
        expect(document.body).not.toHaveTextContent('Retry')
    })
})
