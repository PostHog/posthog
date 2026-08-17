import { AlertMode } from 'products/alerts/frontend/types'

export interface AlertModeOption {
    value: AlertMode
    label: string
    description: string
    'data-attr': string
}

interface AlertModeOptionsInput {
    /** Anomaly detection is available: its flag is on and the insight kind supports it. */
    supportsAnomalyDetection: boolean
    /** Forecasting is available: its flag is on and the insight kind supports it. */
    supportsForecast: boolean
    showAnomalyGuidance: boolean
}

/** Options for the alert mode picker. Each optional mode is gated on its own flag and capability,
 * so turning one on never surfaces the other on an insight kind that cannot run it. */
export function alertModeOptions({
    supportsAnomalyDetection,
    supportsForecast,
    showAnomalyGuidance,
}: AlertModeOptionsInput): AlertModeOption[] {
    const options: AlertModeOption[] = [
        {
            value: 'threshold',
            label: 'Threshold',
            description: 'Alert when a value goes above or below a fixed value you set.',
            'data-attr': 'alertForm-mode-threshold',
        },
    ]
    if (supportsAnomalyDetection) {
        options.push({
            value: 'detector',
            label: 'Anomaly detection',
            description: showAnomalyGuidance
                ? 'Choose this when you want an alert for unusual changes and do not know what threshold to set.'
                : 'Automatically flag unusual changes using statistical models. No fixed value needed.',
            'data-attr': 'alertForm-mode-detector',
        })
    }
    if (supportsForecast) {
        options.push({
            value: 'forecast',
            label: 'Forecast',
            description: 'Alert on where this metric is heading, before it crosses your threshold.',
            'data-attr': 'alertForm-mode-forecast',
        })
    }
    return options
}
