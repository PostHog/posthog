import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { NodeKind } from '~/queries/schema/schema-general'
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

function metricsTile(id: number, language: 'builder' | 'promql'): DashboardType['tiles'][number] {
    const source =
        language === 'builder'
            ? { kind: NodeKind.MetricsQuery, clauses: [{ name: 'a', metricName: 'http.server.duration' }] }
            : { kind: NodeKind.MetricsQuery, clauses: [], language, promql: 'up' }
    return {
        id,
        layouts: {},
        color: null,
        insight: { id, short_id: `m${id}`, query: { kind: NodeKind.InsightVizNode, source } },
    } as unknown as DashboardType['tiles'][number]
}

function renderFilterBar(dashboard: DashboardType, placement: DashboardPlacement): void {
    const props = { id: dashboard.id, dashboard, placement }
    dashboardLogic(props).mount()
    render(
        <BindLogic logic={dashboardLogic} props={props}>
            <DashboardFilterBar />
        </BindLogic>
    )
}

const addFilterButton = (): HTMLButtonElement | null =>
    document.querySelector<HTMLButtonElement>('[data-attr="dashboard-metric-filters-add"]')

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
        renderFilterBar(DASHBOARD, placement)

        expect(screen.getByText('Service')).toBeInTheDocument()
        expect(!!document.querySelector('[data-attr="dashboard-metric-variables-edit"]')).toBe(editable)
        expect(!!document.querySelector('[data-attr="dashboard-metric-variables-add"]')).toBe(editable)
        expect(!!addFilterButton()).toBe(editable)
    })

    it.each([
        ['builder tiles', ['builder', 'builder'], null, 'enabled'],
        ['only PromQL tiles', ['promql'], null, 'hidden'],
        [
            'only PromQL tiles and a saved filter',
            ['promql'],
            [{ key: 'service.name', op: 'eq', value: 'api' }],
            'disabled',
        ],
    ] as const)('shows "Add filter" for a dashboard with %s as %s', (_, languages, metricFilters, expected) => {
        const filters = { ...FILTERS, metricFilters }
        renderFilterBar(
            {
                ...DASHBOARD,
                user_access_level: AccessControlLevel.Editor,
                tiles: languages.map((language, index) => metricsTile(index + 1, language)),
                filters,
                persisted_filters: filters,
            } as unknown as DashboardType,
            DashboardPlacement.Dashboard
        )

        const button = addFilterButton()
        expect(button ? (button.getAttribute('aria-disabled') === 'true' ? 'disabled' : 'enabled') : 'hidden').toBe(
            expected
        )
    })
})
