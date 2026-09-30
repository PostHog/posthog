import { render, within } from '@testing-library/react'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'

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
})
