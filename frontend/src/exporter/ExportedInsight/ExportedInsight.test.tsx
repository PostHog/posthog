import { MOCK_DATA_COLOR_THEMES } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, waitFor } from '@testing-library/react'

import { getHogChart, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { renderWithInsights } from '~/test/insight-testing'
import { InsightModel } from '~/types'

import __funnelTrend from '../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import __funnel from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
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

    it.each([
        ['trends', __trendsLineMulti, 'relative_increase', 'percentage', 0.25, 'TrendsAlertConfig'],
        ['funnel', __funnel, 'absolute_value', 'absolute', 55, 'FunnelsAlertConfig'],
        ['funnel trend', __funnelTrend, 'absolute_value', 'absolute', 55, 'FunnelsAlertConfig'],
    ])(
        'draws the %s alert limit in the export',
        async (_name, fixture, condition, thresholdType, limit, configType) => {
            const insight = structuredClone(fixture) as unknown as InsightModel
            insight.alerts = [
                {
                    id: 'sample-alert',
                    name: 'Sample limit',
                    condition: { type: condition },
                    threshold: { configuration: { type: thresholdType, bounds: { upper: limit } } },
                    config: {
                        type: configType,
                        series_index: 0,
                        check_ongoing_interval: true,
                        metric: 'conversion_from_start',
                    },
                },
            ] as unknown as InsightModel['alerts']
            if (_name === 'trends') {
                insight.result = [{ ...(insight.result as Record<string, unknown>[])[0], data: [40, 60, 80, 120] }]
            }
            renderWithInsights({
                component: (
                    <ExportedInsight
                        insight={insight}
                        themes={MOCK_DATA_COLOR_THEMES}
                        exportOptions={{ legend: false }}
                    />
                ),
            })
            await waitFor(() => {
                expect(
                    getHogChart()
                        .referenceLines()
                        .map((line) => line.label)
                ).toContain('Sample limit Upper Threshold')
            })
        }
    )
})
