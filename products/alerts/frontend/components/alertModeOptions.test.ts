import { alertModeOptions } from './alertModeOptions'

describe('alertModeOptions', () => {
    // Each optional mode is gated on its own flag and capability. An earlier version showed the
    // picker whenever either was enabled but left anomaly detection unconditionally in the list,
    // so the forecast flag alone surfaced anomaly detection on insight kinds that cannot run it.
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
})
