import { MOCK_DATA_COLOR_THEMES } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

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
    function renderAdhoc(fixture: any, legend = false, title?: string): { container: HTMLElement } {
        return renderWithInsights({
            component: (
                <ExporterQueryScene
                    query={fixture.query}
                    queryResults={{ results: fixture.result }}
                    title={title}
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

    it('renders the supplied title inside the exported chart card', () => {
        renderAdhoc(__trendsBarBreakdown, false, 'Weekly signups')

        expect(screen.getByText('Weekly signups')).toHaveClass('ExportedInsight__header__title')
    })

    it('lets the chart draw the quill in-chart legend, like a saved-insight export', async () => {
        const { container } = renderAdhoc(__trendsBarBreakdown, true)

        await waitFor(() => {
            expect(container.querySelector('[data-attr="hog-chart-timeseries-bar-legend"]')).toBeInTheDocument()
        })
        // Exactly one legend: the legacy horizontal legend below the chart must not render too.
        expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
    })
})
