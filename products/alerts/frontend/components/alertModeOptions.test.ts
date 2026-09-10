import { alertModeOptions } from './alertModeOptions'

describe('alertModeOptions', () => {
    it.each([
        ['neither available', false, false, ['threshold']],
        ['anomaly only', true, false, ['threshold', 'detector']],
        ['forecast only', false, true, ['threshold', 'forecast']],
        ['both available', true, true, ['threshold', 'detector', 'forecast']],
    ] as const)('%s', (_, supportsAnomalyDetection, supportsForecast, expected) => {
        const values = alertModeOptions({
            supportsAnomalyDetection,
            supportsForecast,
            showAnomalyGuidance: false,
        }).map((option) => option.value)
        expect(values).toEqual(expected)
    })

    it('swaps the anomaly description when guidance is on', () => {
        const describe_ = (showAnomalyGuidance: boolean): string | undefined =>
            alertModeOptions({ supportsAnomalyDetection: true, supportsForecast: false, showAnomalyGuidance }).find(
                (option) => option.value === 'detector'
            )?.description

        expect(describe_(true)).not.toEqual(describe_(false))
    })
    it('describes forecast without naming one condition or a cycle some intervals never fit', () => {
        const forecast = alertModeOptions({
            supportsAnomalyDetection: false,
            supportsForecast: true,
            showAnomalyGuidance: false,
        }).find((option) => option.value === 'forecast')
        expect(forecast?.description).not.toContain('threshold')
        // Prophet fits a weekly or monthly insight trend only, so naming a weekly pattern here
        // would describe the daily case as if it were every case. See `min_forecast_points` in
        // products/alerts/backend/forecasting/engine.py.
        expect(forecast?.description).not.toMatch(/weekly|seasonal/i)
    })

    it('keeps an unavailable existing forecast visible but prevents selecting it again', () => {
        const disabledReason = 'Forecast alerts are no longer enabled for this project.'
        const forecast = alertModeOptions({
            supportsAnomalyDetection: false,
            supportsForecast: true,
            showAnomalyGuidance: false,
            forecastDisabledReason: disabledReason,
        }).find((option) => option.value === 'forecast')

        expect(forecast?.disabledReason).toBe(disabledReason)
    })
})
