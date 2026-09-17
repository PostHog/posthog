import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagGroupType, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { featureFlagReleaseConditionsLogic } from './featureFlagReleaseConditionsLogic'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const INCOMPLETE_FILTER_MESSAGE = 'Add a value or remove this filter'

// A property picked from the taxonomic list starts with a null value, and the form blocks the save
// while that half-built row is on the flag.
function buildFilters(): FeatureFlagType['filters'] {
    const groups: FeatureFlagGroupType[] = [
        {
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
        },
        {
            properties: [
                {
                    key: 'plan',
                    value: null,
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Person,
                },
            ],
            rollout_percentage: 100,
            variant: null,
            sort_key: 'group-2',
        },
    ]
    return { groups, multivariate: null, payloads: {} }
}

describe('a save blocked by a collapsed condition set', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

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
                '/api/projects/:team/feature_flags/1234/status': { status: 'active', reason: 'mock reason' },
                '/api/projects/:team/actions': { results: [] },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 0, total: 2 }],
            },
        })
        logic = featureFlagLogic({ id: 1234 })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('opens the set that holds the value-less filter, and only that set', async () => {
        const filters = buildFilters()
        logic.actions.setFeatureFlag({ ...NEW_FLAG, id: 1234, key: 'test-flag', filters } as FeatureFlagType)
        render(
            <Provider>
                <FeatureFlagReleaseConditionsCollapsible
                    id="1234"
                    flagId={1234}
                    filters={filters}
                    onChange={logic.actions.setFeatureFlagFilters}
                />
            </Provider>
        )

        // Both sets start collapsed, which renders neither the inline error nor a scroll target.
        await waitFor(() => expect(screen.getByLabelText('Toggle condition 2 details')).toBeInTheDocument())
        expect(document.body).not.toHaveTextContent(INCOMPLETE_FILTER_MESSAGE)

        await expectLogic(logic, () => {
            logic.actions.submitFeatureFlag()
        }).toFinishAllListeners()

        await waitFor(() => expect(document.body).toHaveTextContent(INCOMPLETE_FILTER_MESSAGE))
        expect(featureFlagReleaseConditionsLogic.findMounted({ id: '1234' })?.values.openConditions).toEqual([
            'condition-group-2',
        ])
    })
})
