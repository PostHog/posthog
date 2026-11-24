import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagFilters, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const offCohort = {
    id: 1,
    name: 'Viewed pricing this week',
    is_static: false,
    filters: { properties: { type: 'AND', values: [] } },
    realtime_enabled: false,
    realtime: { state: 'off', ready_at: null, build: null, reason: null, history_limit_days: null },
}

const filters: FeatureFlagFilters = {
    groups: [
        {
            properties: [
                {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 1,
                    operator: PropertyOperator.In,
                    cohort_name: 'Viewed pricing this week',
                },
            ],
            rollout_percentage: 100,
            variant: null,
            sort_key: 'group-1',
        },
    ],
    multivariate: null,
    payloads: {},
}

describe('feature flag release conditions cohort realtime notice', () => {
    beforeEach(async () => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/cohorts/': toPaginatedResponse([offCohort]),
                '/api/projects/:team/cohorts/:id/': offCohort,
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
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            editor: 'FeatureFlagReleaseConditions',
            component: <FeatureFlagReleaseConditions id="1234" filters={filters} onChange={jest.fn()} />,
        },
        {
            editor: 'FeatureFlagReleaseConditionsCollapsible',
            component: (
                <FeatureFlagReleaseConditionsCollapsible
                    id="1234"
                    flagId={1234}
                    filters={filters}
                    onChange={jest.fn()}
                />
            ),
        },
    ])('$editor offers to turn on realtime for a cohort a condition set targets', async ({ component }) => {
        render(<Provider>{component}</Provider>)

        expect(await screen.findByText('Turn on realtime')).toBeInTheDocument()
    })

    // Only this editor renders its read-only view from the same condition set markup as the editable one.
    it('FeatureFlagReleaseConditions shows no notice when read only', async () => {
        render(
            <Provider>
                <FeatureFlagReleaseConditions id="1234" filters={filters} onChange={jest.fn()} readOnly />
            </Provider>
        )

        // The read-only view names the cohort once it renders, and the shared model already holds its state.
        await waitFor(() => {
            expect(screen.getAllByText(/Viewed pricing this week/).length).toBeGreaterThan(0)
        })
        expect(document.querySelector('[data-attr="cohort-flag-targeting-notice"]')).not.toBeInTheDocument()
    })
})
