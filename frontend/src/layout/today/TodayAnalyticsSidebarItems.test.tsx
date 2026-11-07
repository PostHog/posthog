import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { TodayAnalyticsMetric } from './TodayAnalyticsMetric'
import { TodayAnalyticsSidebarButton } from './TodayAnalyticsSidebarButton'
import { TodayPaneSearchList } from './TodayPaneSearchList'

describe('Analytics sidebar options', () => {
    beforeEach(initKeaTests)
    afterEach(cleanup)

    it('keeps a pending metric insight available as a link and keyboard option', () => {
        useMocks({ get: { '/api/projects/:team_id/insights/': async () => await new Promise<never>(() => {}) } })

        const { container } = render(
            <TodayPaneSearchList query="" onQueryChange={jest.fn()} searchLabel="Search analytics" dataAttr="search">
                <TodayAnalyticsMetric
                    item={{ type: 'metric', insight: 'aB3dE5fG', label: 'Signups this week' }}
                    value="growth:0"
                    active={false}
                />
            </TodayPaneSearchList>
        )

        const link = container.querySelector('[data-attr="analytics-sidebar-metric"]')
        expect(link?.getAttribute('role')).toBe('option')
        expect(link?.textContent).toContain('Signups this week')
        expect(link?.getAttribute('href')).toContain('aB3dE5fG')
    })

    it('formats a loaded metric with the project currency and hides a disabled change', async () => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, base_currency: CurrencyCode.EUR })
        useMocks({
            get: {
                '/api/projects/:team_id/insights/': {
                    results: [
                        {
                            query: {
                                kind: 'InsightVizNode',
                                source: {
                                    kind: 'TrendsQuery',
                                    trendsFilter: { aggregationAxisFormat: 'currency', metricShowChange: false },
                                },
                            },
                            result: [{ count: 125, data: [10, 20, 30], labels: ['Mon', 'Tue', 'Wed'] }],
                        },
                    ],
                },
            },
        })

        const { container } = render(
            <TodayPaneSearchList query="" onQueryChange={jest.fn()} searchLabel="Search analytics" dataAttr="search">
                <TodayAnalyticsMetric
                    item={{ type: 'metric', insight: 'aB3dE5fG', label: 'Revenue' }}
                    value="growth:0"
                    active={false}
                />
            </TodayPaneSearchList>
        )

        expect(await screen.findByText(/€125/)).toBeTruthy()
        expect(container.querySelector('[data-attr="metric-change-pill"]')).toBeNull()
    })

    it.each(['primary', 'outline'] as const)('includes a %s custom button in arrow navigation', (variant) => {
        const { container } = render(
            <TodayPaneSearchList query="" onQueryChange={jest.fn()} searchLabel="Search analytics" dataAttr="search">
                <TodayAnalyticsSidebarButton
                    value="growth:0"
                    sectionId="growth"
                    target={{
                        type: 'button',
                        to: { kind: 'page', page: 'new_insight' },
                        label: 'New insight',
                        variant,
                    }}
                />
            </TodayPaneSearchList>
        )

        const input = container.querySelector('[data-attr="search"]') as HTMLInputElement
        const button = container.querySelector('[data-attr="analytics-sidebar-growth-button"]')
        expect(input.getAttribute('role')).toBe('combobox')
        expect(button?.getAttribute('role')).toBe('option')
        expect(button?.textContent).toContain('New insight')
        fireEvent.keyDown(input, { key: 'ArrowDown' })
        expect(button?.hasAttribute('data-highlighted')).toBe(true)
        expect(button?.getAttribute('href')).toContain('insights/new')
        fireEvent.keyDown(input, { key: 'Enter' })
        expect(router.values.location.pathname).toContain('insights/new')
    })
})
