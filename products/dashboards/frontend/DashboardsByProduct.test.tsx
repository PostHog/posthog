import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { productEmptyStateGateActivation } from 'lib/components/ProductEmptyState/gateRender'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { Scene } from 'scenes/sceneTypes'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DashboardsByProduct } from './DashboardsByProduct'
import { dashboardsEmptyState } from './emptyState/dashboardsEmptyState'

function cardTitles(): (string | null)[] {
    return screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
}

describe('dashboards by product', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]: 'test',
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'test',
        })
        eventUsageLogic.mount()
    })

    it.each([
        [undefined, 'on'],
        [DashboardsTab.All, 'on'],
        [DashboardsTab.Yours, 'on'],
        [DashboardsTab.Pinned, 'on'],
        [DashboardsTab.ByProduct, 'off'],
        [DashboardsTab.CrossProject, 'off'],
    ])('applies dashboard setup to tab %s: %s', (tab, expected) => {
        expect(
            productEmptyStateGateActivation({
                emptyState: dashboardsEmptyState,
                activeSceneId: Scene.Dashboards,
                params: {},
                searchParams: { tab },
                featureFlags: featureFlagLogic.values.featureFlags,
                receivedFeatureFlags: true,
                forcedMode: null,
            })
        ).toBe(expected)
    })

    it('keeps product dashboards reachable from the setup screen', () => {
        const SceneNav = dashboardsEmptyState.SceneNav!
        render(<SceneNav />)
        fireEvent.click(screen.getByText('By product'))
        expect(dashboardsLogic.values.currentTab).toBe(DashboardsTab.ByProduct)
    })

    it('records one tab visit when cards render, without counting rerenders', () => {
        const report = jest.spyOn(eventUsageLogic.actions, 'reportDashboardsByProductViewed')
        const { rerender } = render(<DashboardsByProduct />)
        expect(report).toHaveBeenCalledTimes(1)
        rerender(<DashboardsByProduct />)
        expect(report).toHaveBeenCalledTimes(1)
        report.mockRestore()
    })

    it('moves starred products first and reflects removal without changing the remaining order', async () => {
        render(<DashboardsByProduct />)
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        await expectLogic(projectTreeDataLogic, () =>
            projectTreeDataLogic.actions.loadShortcutsSuccess([
                { id: 'ai', path: 'LLM analytics', type: 'llm_analytics' },
                { id: 'errors', path: 'Error tracking', type: 'error_tracking' },
            ])
        )
        expect(cardTitles()).toEqual([
            'AI observability',
            'Error tracking',
            'Product analytics',
            'Web analytics',
            'Customer analytics',
            'Marketing analytics',
            'MCP analytics',
        ])
        expect(screen.getAllByLabelText('Starred in sidebar')).toHaveLength(2)
        await expectLogic(projectTreeDataLogic, () => projectTreeDataLogic.actions.loadShortcutsSuccess([]))
        expect(cardTitles()).toEqual([
            'Product analytics',
            'Web analytics',
            'Customer analytics',
            'Marketing analytics',
            'AI observability',
            'MCP analytics',
            'Error tracking',
        ])
        expect(screen.queryByLabelText('Starred in sidebar')).toBeNull()
    })

    it('hides the control variant and keeps product analytics gated even when starred', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]: 'control',
        })
        const { rerender } = render(<DashboardsByProduct />)
        expect(screen.queryByText('Dashboards by product')).toBeNull()
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        await expectLogic(featureFlagLogic, () =>
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]: 'test',
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'control',
            })
        )
        await expectLogic(projectTreeDataLogic, () =>
            projectTreeDataLogic.actions.loadShortcutsSuccess([
                { id: 'product', path: 'Product analytics', type: 'product_analytics' },
            ])
        )
        rerender(<DashboardsByProduct />)
        expect(cardTitles()).not.toContain('Product analytics')
    })

    it.each([
        ['click', {}, true],
        ['click', { metaKey: true }, true],
        ['click', { ctrlKey: true }, true],
        ['auxClick', { button: 1 }, true],
        ['auxClick', { button: 2 }, false],
    ] as const)('records navigation clicks for %s with %j', (eventName, options, countsAsClick) => {
        const report = jest.spyOn(eventUsageLogic.actions, 'reportDashboardByProductClicked')
        const { container } = render(<DashboardsByProduct />)
        const card = container.querySelector<HTMLAnchorElement>('[data-attr="dashboard-by-product-mcp"]')!
        card.addEventListener('click', (event) => event.preventDefault())
        fireEvent(
            card,
            new MouseEvent(eventName === 'auxClick' ? 'auxclick' : 'click', {
                bubbles: true,
                cancelable: true,
                ...options,
            })
        )
        expect(report.mock.calls).toEqual(countsAsClick ? [['mcp']] : [])
        report.mockRestore()
    })
})
