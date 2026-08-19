import { AlertMode } from 'products/alerts/frontend/types'

export interface AlertModeOption {
    value: AlertMode
    label: string
    description: string
    'data-attr': string
}

interface AlertModeOptionsInput {
    supportsAnomalyDetection: boolean
    supportsForecast: boolean
    showAnomalyGuidance: boolean
}

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
            description: 'Alert on where this metric is heading, using its trend and weekly pattern.',
            'data-attr': 'alertForm-mode-forecast',
        })
    }
    return options
}
