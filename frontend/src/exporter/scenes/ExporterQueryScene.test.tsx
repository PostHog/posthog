import { MOCK_DATA_COLOR_THEMES } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { renderWithInsights } from '~/test/insight-testing'

import __trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import __trendsPie from '../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import ExporterQueryScene from './ExporterQueryScene'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

describe('ExporterQueryScene', () => {
    function renderAdhoc(fixture: any, legend = false): { container: HTMLElement } {
        return renderWithInsights({
            component: (
                <ExporterQueryScene
                    query={fixture.query}
                    queryResults={{ results: fixture.result }}
                    themes={MOCK_DATA_COLOR_THEMES}
                    exportOptions={{ legend }}
                />
            ),
        })
    }

    // An ad-hoc export has no cachedInsight, so the query only reaches insightDataLogic via insightProps.
    // Miss that and it falls back to a bare TrendsQuery, rendering every export as a plain line chart.
    it.each([
        ['bar', __trendsBarBreakdown, 'trend-bar-graph'],
        ['pie', __trendsPie, 'trend-pie-graph'],
    ])('renders the %s display the query asks for', async (_name, fixture, dataAttr) => {
        const { container } = renderAdhoc(fixture)

        await waitFor(() => {
            expect(container.querySelector(`[data-attr="${dataAttr}"]`)).toBeInTheDocument()
        })
    })

    it('lets the chart draw the quill in-chart legend, like a saved-insight export', async () => {
        const { container } = renderAdhoc(__trendsBarBreakdown, true)

        await waitFor(() => {
            expect(container.querySelector('[data-attr="hog-chart-timeseries-bar-legend"]')).toBeInTheDocument()
        })
        // Exactly one legend: the legacy horizontal legend below the chart must not render too.
        expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
    })

    // A shared report has no editor session, so hiding a series can't be persisted — but it must still
    // apply to the chart the viewer is looking at instead of silently snapping back.
    it('hides a series when the viewer toggles it off in the legend', async () => {
        const { container } = renderAdhoc(__trendsBarBreakdown, true)

        const legendAttr = '[data-attr="hog-chart-timeseries-bar-legend"]'
        await waitFor(() => {
            expect(container.querySelector(legendAttr)).toBeInTheDocument()
        })
        const items = container.querySelectorAll(`${legendAttr} button`)
        expect(items.length).toBeGreaterThan(1)

        await userEvent.click(items[0])

        // Dimmed in the legend (so it can be restored) and dropped from the chart itself.
        await waitFor(() => {
            expect(container.querySelector(`${legendAttr} .opacity-40`)).toBeInTheDocument()
        })
        expect(container.querySelector('canvas[aria-label]')).toHaveAttribute('aria-label', 'Chart with 2 data series')
    })
})
