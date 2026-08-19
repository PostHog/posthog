import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagGroupType, FeatureFlagType } from '~/types'

import { EARLY_ACCESS_GROUP_TARGETING_DISABLED_REASON } from './constants'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

function buildFilters(): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties: [],
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return { groups: [group], multivariate: null, payloads: {} }
}

async function openTargetByAndGetGroupOption(): Promise<HTMLButtonElement> {
    await waitFor(() => {
        expect(document.querySelector('[data-attr="condition-set-0-aggregation"]')).toBeInTheDocument()
    })
    await userEvent.click(document.querySelector('[data-attr="condition-set-0-aggregation"]')!)

    // 'organizations' is seeded by initKeaTests() from MOCK_DEFAULT_TEAM.group_types;
    // the groups_types API mock returns an empty list, so it is not the source here
    let option: HTMLButtonElement | undefined
    await waitFor(() => {
        option = Array.from(document.querySelectorAll('button')).find(
            (button) => button.textContent === 'organizations'
        )
        expect(option).not.toBeUndefined()
    })
    return option!
}

describe('release condition group targeting on early access flags', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/cohorts/': { results: [], next: null, count: 0 },
                '/api/projects/:team/actions': { results: [] },
                '/api/projects/:team/feature_flags/1234/': {
                    id: 1234,
                    key: 'test-flag',
                    filters: { groups: [], multivariate: null, payloads: {} },
                },
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

    it('disables the group type when the flag is linked to an early access feature', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditionsCollapsible
                    id="1234"
                    flagId={1234}
                    filters={buildFilters()}
                    onChange={jest.fn()}
                    hasEarlyAccessFeatures
                />
            </Provider>
        )

        const organizations = await openTargetByAndGetGroupOption()

        expect(organizations).toHaveAttribute('aria-disabled', 'true')

        // The gate must disable only group types, not the whole "Target by" list
        const users = Array.from(document.querySelectorAll('[role="menuitem"]')).find(
            (el) => el.textContent === 'Users'
        )
        expect(users).toHaveAttribute('aria-disabled', 'false')

        await userEvent.hover(organizations)
        await waitFor(() => {
            expect(document.body).toHaveTextContent(EARLY_ACCESS_GROUP_TARGETING_DISABLED_REASON)
        })

        // Clicking the disabled option must not change the aggregation
        await userEvent.click(organizations)
        expect(document.querySelector('[data-attr="condition-set-0-aggregation"]')).toHaveTextContent('Users')
    })

    it('leaves the group type selectable when no early access feature is linked', async () => {
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

        const organizations = await openTargetByAndGetGroupOption()

        expect(organizations).toHaveAttribute('aria-disabled', 'false')
    })
})
