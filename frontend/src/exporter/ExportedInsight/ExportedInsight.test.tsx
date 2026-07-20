import { MOCK_DATA_COLOR_THEMES } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { renderWithInsights } from '~/test/insight-testing'
import { InsightModel } from '~/types'

import __trendsLineMulti from '../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import { ExportedInsight } from './ExportedInsight'

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

describe('ExportedInsight', () => {
    function renderExported(legend: boolean): { container: HTMLElement } {
        return renderWithInsights({
            component: (
                <ExportedInsight
                    insight={__trendsLineMulti as unknown as InsightModel}
                    themes={MOCK_DATA_COLOR_THEMES}
                    exportOptions={{ legend }}
                />
            ),
        })
    }

    it('lets the chart draw the quill in-chart legend when the legend export option is on', async () => {
        const { container } = renderExported(true)

        await waitFor(() => {
            expect(container.querySelector('[data-attr="hog-chart-timeseries-line-legend"]')).toBeInTheDocument()
        })
        // Exactly one legend: the legacy horizontal legend below the chart must not render too.
        expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
    })

    it('renders no legend at all when the legend export option is off', async () => {
        const { container } = renderExported(false)

        await waitFor(() => {
            expect(container.querySelector('canvas[aria-label]')).toBeInTheDocument()
        })
        expect(container.querySelector('[data-attr="hog-chart-timeseries-line-legend"]')).not.toBeInTheDocument()
        expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
    })
})
