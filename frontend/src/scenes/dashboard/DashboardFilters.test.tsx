import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardPlacement, DashboardType } from '~/types'

import { DashboardFilterBar } from './DashboardFilters'
import { dashboardLogic } from './dashboardLogic'

const FILTERS = {
    metricVariables: [{ name: 'service', label: 'Service', source: 'custom', customValues: ['api', 'web'] }],
}

const DASHBOARD = {
    id: 7,
    name: 'HTTP server',
    pinned: false,
    tiles: [],
    tags: [],
    created_at: '2020-01-01T00:00:00Z',
    created_by: null,
    last_accessed_at: '2020-01-01T00:00:00Z',
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    user_access_level: AccessControlLevel.Viewer,
    filters: FILTERS,
    persisted_filters: FILTERS,
    variables: {},
} as unknown as DashboardType

describe('DashboardFilterBar', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.METRICS_DASHBOARD_CONTROLS], {
            [FEATURE_FLAGS.METRICS_DASHBOARD_CONTROLS]: true,
        })
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        [DashboardPlacement.Dashboard, true],
        [DashboardPlacement.Builtin, false],
    ])('shows the metric variables in the %s placement, with the editor %s', (placement, editable) => {
        const props = { id: DASHBOARD.id, dashboard: DASHBOARD, placement }
        dashboardLogic(props).mount()

        render(
            <BindLogic logic={dashboardLogic} props={props}>
                <DashboardFilterBar />
            </BindLogic>
        )

        expect(screen.getByText('Service')).toBeInTheDocument()
        expect(!!document.querySelector('[data-attr="dashboard-metric-variables-edit"]')).toBe(editable)
    })
})
