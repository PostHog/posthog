import '@testing-library/jest-dom'

// The tile only renders its visualization once in view, which jsdom never reports.
jest.mock('react-intersection-observer', () => ({
    useInView: () => ({ ref: () => {}, inView: true }),
}))

import { cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { renderWithInsights } from '~/test/insight-testing'
import { DashboardPlacement, QueryBasedInsightModel } from '~/types'

import __trendsBarBreakdown from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import { InsightCard } from './InsightCard'

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

const LEGEND = '[data-attr="hog-chart-timeseries-bar-legend"]'

describe('InsightCard on a shared dashboard', () => {
    function renderPublicTile(): HTMLElement {
        const fixture = __trendsBarBreakdown as any
        const insight = {
            ...fixture,
            short_id: 'sharedcard',
            query: {
                ...fixture.query,
                source: {
                    ...fixture.query.source,
                    trendsFilter: { ...fixture.query.source.trendsFilter, showLegend: true },
                },
            },
        } as unknown as QueryBasedInsightModel

        const { container } = renderWithInsights({
            component: (
                <InsightCard
                    insight={insight}
                    dashboardId={7}
                    placement={DashboardPlacement.Public}
                    showResizeHandles={false}
                    updateColor={() => {}}
                    doNotLoad
                />
            ),
        })
        return container
    }

    // A viewer of a shared dashboard has no editor session, so hiding a series can't be persisted — but
    // it must still apply to the chart in front of them rather than being inert.
    it('hides a series when the viewer toggles it off in the legend', async () => {
        const container = renderPublicTile()

        await waitFor(() => {
            expect(container.querySelector(LEGEND)).toBeInTheDocument()
        })
        const items = container.querySelectorAll(`${LEGEND} button`)
        expect(items.length).toBeGreaterThan(1)

        await userEvent.click(items[0])

        // Dimmed in the legend (so it can be restored) and dropped from the chart itself.
        await waitFor(() => {
            expect(container.querySelector(`${LEGEND} .opacity-40`)).toBeInTheDocument()
        })
        expect(container.querySelector('canvas[aria-label]')).toHaveAttribute('aria-label', 'Chart with 2 data series')
    })
})
