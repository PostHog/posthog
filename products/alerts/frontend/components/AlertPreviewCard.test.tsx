import { render, within } from '@testing-library/react'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { deriveMetricsAlertPreviewSeries } from 'products/alerts/frontend/logic/metricsAlertPreview'

import { AlertPreviewCard, AlertPreviewCardProps } from './AlertPreviewCard'

// Trend results declare `data` as a required array, but breakdown rows can arrive without it.
type BreakdownSeries = NonNullable<AlertPreviewCardProps['trendsBreakdownSeries']>
const seriesWithoutData = [{ key: 'chrome', label: 'Chrome' }] as BreakdownSeries
const seriesWithMissingAndPresentData = [
    { key: 'chrome', label: 'Chrome' },
    { key: 'safari', label: 'Safari', data: [10, 25, 60] },
] as BreakdownSeries

const EMPTY_BREAKDOWN_TEXT = 'No activity to preview across breakdown values.'

describe('AlertPreviewCard', () => {
    const alertForm = {
        name: 'Preview alert',
        enabled: true,
        config: { type: 'TrendsAlertConfig', series_index: 0 },
        condition: { type: AlertConditionType.ABSOLUTE_VALUE },
        threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: { upper: 60, lower: 20 } } },
    } as AlertFormType

    // No labels are passed, because breakdown rows often have none. The chart then builds labels
    // from the first series' data, which is the path that crashed.
    function renderCard(trendsBreakdownSeries: BreakdownSeries): HTMLElement {
        const { container } = render(
            <AlertPreviewCard
                alertForm={alertForm}
                trendsValues={[20, 30, 40]}
                isBreakdown
                trendsBreakdownSeries={trendsBreakdownSeries}
                funnelPreview={null}
                hogqlPreview={null}
            />
        )
        return container
    }

    it('shows the empty state when every breakdown series has no data', () => {
        const container = renderCard(seriesWithoutData)

        expect(within(container).getByText(EMPTY_BREAKDOWN_TEXT)).toBeTruthy()
    })

    it('charts the breakdown series that do have data', () => {
        const container = renderCard(seriesWithMissingAndPresentData)

        expect(within(container).queryByText(EMPTY_BREAKDOWN_TEXT)).toBeNull()
    })

    it.each([
        ['builder', false, 'Preview'],
        ['grouped', true, 'All series'],
    ])('charts a new metrics alert from the %s insight results', (_, grouped, title) => {
        const points = [
            { time: '2026-11-25T10:00:00Z', value: 10 },
            { time: '2026-11-25T11:00:00Z', value: null },
        ]
        const results = grouped
            ? [
                  { labels: { service: 'api' }, metricName: 'latency', points },
                  { labels: { service: 'web' }, metricName: 'latency', points },
              ]
            : [{ labels: {}, metricName: 'latency', points }]
        const { container } = render(
            <AlertPreviewCard
                alertForm={{ ...alertForm, config: { type: 'MetricsAlertConfig' } } as AlertFormType}
                trendsValues={null}
                funnelPreview={null}
                hogqlPreview={null}
                metricsPreview={deriveMetricsAlertPreviewSeries({ results }, true)}
            />
        )

        expect(within(container).queryByText('No insight data available to preview.')).toBeNull()
        expect(within(container).getByText(title)).toBeTruthy()
    })

    it('charts a metrics preview too large to spread into Math.max', () => {
        const metricsForm = { ...alertForm, config: { type: 'MetricsAlertConfig' } } as AlertFormType
        const data = Array.from({ length: 200_000 }, (_, i) => i % 100)

        expect(() =>
            render(
                <AlertPreviewCard
                    alertForm={metricsForm}
                    trendsValues={null}
                    funnelPreview={null}
                    hogqlPreview={null}
                    metricsPreview={{ rows: [{ key: '0', label: 'latency', data }], labels: [] }}
                />
            )
        ).not.toThrow()
    })

    it('offers a retry when the metrics preview fails to load', () => {
        const { container } = render(
            <AlertPreviewCard
                alertForm={{ ...alertForm, config: { type: 'MetricsAlertConfig' } } as AlertFormType}
                trendsValues={null}
                funnelPreview={null}
                hogqlPreview={null}
                metricsPreview={null}
                metricsPreviewFailed
                onRetryMetricsPreview={() => {}}
            />
        )

        expect(within(container).getByText("Couldn't load metric data for the preview.")).toBeTruthy()
        expect(within(container).getByText('Try again')).toBeTruthy()
        expect(within(container).queryByText('No insight data available to preview.')).toBeNull()
    })

    it.each([false, true])('explains when the delayed %s preview runs out of loaded history', (isBreakdown) => {
        const { container } = render(
            <AlertPreviewCard
                alertForm={alertForm}
                trendsValues={[]}
                isBreakdown={isBreakdown}
                trendsBreakdownSeries={isBreakdown ? [{ key: 'chrome', label: 'Chrome', data: [] }] : undefined}
                funnelPreview={null}
                hogqlPreview={null}
                previewHistoryTooShort
            />
        )

        expect(within(container).getByText(/date range is too short to preview this delay/)).toBeTruthy()
        expect(within(container).queryByText(EMPTY_BREAKDOWN_TEXT)).toBeNull()
        expect(within(container).queryByText('No insight data available to preview.')).toBeNull()
    })
})
