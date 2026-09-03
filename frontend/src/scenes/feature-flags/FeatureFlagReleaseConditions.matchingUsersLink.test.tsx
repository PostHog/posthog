import { MOCK_GROUP_TYPES } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagGroupType, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

// `aggregation_group_type_index` is set at flag level only, so the condition has to inherit it. That
// resolution happens at the call site and is invisible to `matchingActorsUrl`'s own tests.
function buildFilters(aggregationGroupTypeIndex?: number): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties: [
            {
                key: 'email',
                value: 'is_set',
                operator: PropertyOperator.IsSet,
                type: PropertyFilterType.Person,
            },
        ],
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return {
        groups: [group],
        multivariate: null,
        payloads: {},
        aggregation_group_type_index: aggregationGroupTypeIndex,
    }
}

describe('feature flag release conditions matching users link', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/feature_flags/1234/': {
                    id: 1234,
                    key: 'test-flag',
                    filters: { groups: [], multivariate: null, payloads: {} },
                },
                '/api/projects/:team/actions': { results: [] },
                '/api/projects/:team/groups_types': MOCK_GROUP_TYPES,
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

    const cases = [
        [
            'FeatureFlagReleaseConditions',
            <FeatureFlagReleaseConditions id="1234" filters={buildFilters()} onChange={jest.fn()} />,
            'View matching users',
            '/persons',
        ],
        [
            'FeatureFlagReleaseConditionsCollapsible',
            <FeatureFlagReleaseConditionsCollapsible
                id="1234"
                flagId={1234}
                filters={buildFilters()}
                onChange={jest.fn()}
            />,
            'View matching users',
            '/persons',
        ],
        [
            'FeatureFlagReleaseConditions, group-targeted',
            <FeatureFlagReleaseConditions id="1234" filters={buildFilters(0)} onChange={jest.fn()} />,
            'View matching organizations',
            '/groups/0',
        ],
        [
            'FeatureFlagReleaseConditionsCollapsible, group-targeted',
            <FeatureFlagReleaseConditionsCollapsible
                id="1234"
                flagId={1234}
                filters={buildFilters(0)}
                onChange={jest.fn()}
            />,
            'View matching organizations',
            '/groups/0',
        ],
    ] as const

    test.each(cases)(
        '%s links a condition to the matching actors once counts load',
        async (_name, component, linkText, expectedPath) => {
            const { getByText } = render(<Provider>{component}</Provider>)

            await waitFor(() => {
                const link = getByText(linkText).closest('a')
                expect(link).toBeInTheDocument()
                expect(link).toHaveAttribute('href', expect.stringContaining(expectedPath))
                // The condition's own properties have to reach the link, not just the actor list route.
                expect(link).toHaveAttribute('href', expect.stringContaining('email'))
            })
        }
    )
})
