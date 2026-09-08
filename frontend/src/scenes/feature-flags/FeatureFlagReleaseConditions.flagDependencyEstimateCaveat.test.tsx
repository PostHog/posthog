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

const personFilter = {
    key: 'email',
    value: 'is_set',
    operator: PropertyOperator.IsSet,
    type: PropertyFilterType.Person,
} as const

const flagDependencyFilter = {
    key: '42',
    value: true,
    operator: PropertyOperator.FlagEvaluatesTo,
    type: PropertyFilterType.Flag,
} as const

function buildFilters(withFlagDependency: boolean, groupCount = 1): FeatureFlagType['filters'] {
    const groups: FeatureFlagGroupType[] = Array.from({ length: groupCount }, (_, index) => ({
        properties: withFlagDependency ? [personFilter, flagDependencyFilter] : [personFilter],
        rollout_percentage: 100,
        variant: null,
        sort_key: `group-${index + 1}`,
    }))
    return { groups, multivariate: null, payloads: {} }
}

const CAVEAT = 'This estimate leaves out the flag dependency in this condition.'
const COUNT_CAVEAT_MARKER = 'flag-dependency-condition-count-caveat'

describe('feature flag release conditions flag dependency estimate caveat', () => {
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
                '/api/projects/:team/feature_flags/bulk_keys/': { keys: { '42': 'beta-banner' } },
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 7, total: 7 }],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    // The count the editors render comes from a query that can't express a flag dependency, so it
    // reports the audience the rest of the filters match. Both editors have to say so.
    const cases = [
        [
            'FeatureFlagReleaseConditions',
            <FeatureFlagReleaseConditions id="1234" filters={buildFilters(true)} onChange={jest.fn()} />,
            true,
        ],
        [
            'FeatureFlagReleaseConditionsCollapsible',
            <FeatureFlagReleaseConditionsCollapsible
                id="1234"
                flagId={1234}
                filters={buildFilters(true)}
                onChange={jest.fn()}
            />,
            true,
        ],
        [
            'FeatureFlagReleaseConditions, no flag dependency',
            <FeatureFlagReleaseConditions id="1234" filters={buildFilters(false)} onChange={jest.fn()} />,
            false,
        ],
        [
            'FeatureFlagReleaseConditionsCollapsible, no flag dependency',
            <FeatureFlagReleaseConditionsCollapsible
                id="1234"
                flagId={1234}
                filters={buildFilters(false)}
                onChange={jest.fn()}
            />,
            false,
        ],
    ] as const

    test.each(cases)(
        '%s caveats the estimate only when the condition depends on a flag',
        async (_name, component, expectsCaveat) => {
            const { getByText } = render(<Provider>{component}</Provider>)

            // The caveat sits inside the estimate block, so wait for the count before reading it.
            await waitFor(() => {
                expect(getByText(/Filters match:/)).toBeInTheDocument()
            })

            if (expectsCaveat) {
                expect(getByText(CAVEAT, { exact: false })).toBeInTheDocument()
            } else {
                expect(document.body).not.toHaveTextContent(CAVEAT)
            }
        }
    )

    // A flag with more than one condition renders every condition collapsed, so the header count is
    // the only estimate on screen and has to carry the qualifier itself.
    test.each([
        ['depends on a flag', true, 2],
        ['does not depend on a flag', false, 0],
    ] as const)(
        'FeatureFlagReleaseConditionsCollapsible marks the collapsed header count when the condition %s',
        async (_name, withFlagDependency, expectedMarkers) => {
            const { container, getAllByText } = render(
                <Provider>
                    <FeatureFlagReleaseConditionsCollapsible
                        id="1234"
                        flagId={1234}
                        filters={buildFilters(withFlagDependency, 2)}
                        onChange={jest.fn()}
                    />
                </Provider>
            )

            await waitFor(() => {
                expect(getAllByText(/7 users/)).toHaveLength(2)
            })

            expect(container.querySelectorAll(`[data-attr="${COUNT_CAVEAT_MARKER}"]`)).toHaveLength(expectedMarkers)
            expect(document.body).not.toHaveTextContent(CAVEAT)
        }
    )
})
