import { render, within } from '@testing-library/react'

import {
    AlertCalculationInterval,
    AlertConditionType,
    ForecastConditionType,
    ForecastEngineType,
    ForecastTargetDirection,
    InsightThresholdType,
} from '~/queries/schema/schema-general'

import type { AlertFormType } from '../logic/alertFormLogic'
import { AlertPreviewCard, AlertPreviewCardProps } from './AlertPreviewCard'

// Trend results declare `data` as a required array, but breakdown rows can arrive without it.
type BreakdownSeries = NonNullable<AlertPreviewCardProps['trendsBreakdownSeries']>
const seriesWithoutData = [{ key: 'chrome', label: 'Chrome' }] as BreakdownSeries
const seriesWithMissingAndPresentData = [
    { key: 'chrome', label: 'Chrome' },
    { key: 'safari', label: 'Safari', data: [10, 25, 60] },
] as BreakdownSeries

const EMPTY_BREAKDOWN_TEXT = 'No activity to preview across breakdown values.'
const RUN_PREVIEW_TEXT = 'Run Preview forecast to see it here.'
const SET_THRESHOLD_TEXT = 'Set less than or more than to preview this alert.'

describe('AlertPreviewCard', () => {
    const alertForm = (overrides: Partial<AlertFormType> = {}): AlertFormType =>
        ({
            name: 'My alert',
            enabled: true,
            calculation_interval: AlertCalculationInterval.DAILY,
            condition: { type: AlertConditionType.ABSOLUTE_VALUE },
            config: { type: 'TrendsAlertConfig', series_index: 0 },
            threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: { upper: 100 } } },
            ...overrides,
        }) as unknown as AlertFormType

    const targetByDate = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.TARGET_BY_DATE,
        target: 1000,
        target_direction: ForecastTargetDirection.AT_LEAST,
        target_date: '2026-12-01',
    }

    const futureBreach = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 7,
    }

    const renderCard = (overrides: Partial<AlertFormType> = {}): HTMLElement =>
        render(
            <AlertPreviewCard
                alertForm={alertForm(overrides)}
                trendsValues={[10, 20, 30]}
                funnelPreview={null}
                hogqlPreview={null}
            />
        ).container

    // No labels are passed, because breakdown rows often have none. The chart then builds labels
    // from the first series' data, which is the path that crashed.
    function renderBreakdownCard(trendsBreakdownSeries: BreakdownSeries): HTMLElement {
        return render(
            <AlertPreviewCard
                alertForm={alertForm()}
                trendsValues={[20, 30, 40]}
                isBreakdown
                trendsBreakdownSeries={trendsBreakdownSeries}
                funnelPreview={null}
                hogqlPreview={null}
            />
        ).container
    }

    it('shows the empty state when every breakdown series has no data', () => {
        const container = renderBreakdownCard(seriesWithoutData)

        expect(within(container).getByText(EMPTY_BREAKDOWN_TEXT)).toBeTruthy()
    })

    it('charts the breakdown series that do have data', () => {
        const container = renderBreakdownCard(seriesWithMissingAndPresentData)

        expect(within(container).queryByText(EMPTY_BREAKDOWN_TEXT)).toBeNull()
    })

    // Before the first run the card has no result, but it still has to describe the forecast.
    it('titles the card Forecast before the first run', () => {
        expect(renderCard({ forecast_config: targetByDate } as Partial<AlertFormType>).textContent).toContain(
            'Forecast'
        )
    })

    it('points at the button that actually runs the preview', () => {
        expect(renderCard({ forecast_config: targetByDate } as Partial<AlertFormType>).textContent).toContain(
            RUN_PREVIEW_TEXT
        )
    })

    // Selecting Forecast on an insight with no goal lines lands on an upcoming-breach config with no
    // bounds, where the Preview forecast button is disabled until a bound is set.
    it.each([
        ['asks for a threshold when an upcoming-breach forecast has none', {}, SET_THRESHOLD_TEXT, RUN_PREVIEW_TEXT],
        ['keeps pointing at the button once a bound is set', { upper: 100 }, RUN_PREVIEW_TEXT, SET_THRESHOLD_TEXT],
    ])('%s', (_name, bounds, shown, hidden) => {
        const text = renderCard({
            forecast_config: futureBreach,
            threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds } },
        } as Partial<AlertFormType>).textContent

        expect(text).toContain(shown)
        expect(text).not.toContain(hidden)
    })

    it('keeps the plain preview title for a threshold alert', () => {
        const text = renderCard().textContent
        expect(text).toContain('Preview')
        expect(text).not.toContain('Forecast')
    })
})
