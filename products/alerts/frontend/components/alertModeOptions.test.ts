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
    it('describes forecast without naming only one of its conditions', () => {
        const forecast = alertModeOptions({
            supportsAnomalyDetection: false,
            supportsForecast: true,
            showAnomalyGuidance: false,
        }).find((option) => option.value === 'forecast')
        expect(forecast?.description).not.toContain('threshold')
    })
})
