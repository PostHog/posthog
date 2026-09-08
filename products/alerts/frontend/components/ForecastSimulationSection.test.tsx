import { render } from '@testing-library/react'

import {
    AlertCalculationInterval,
    AlertConditionType,
    ForecastConditionType,
    ForecastEngineType,
    InsightThresholdType,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'

import type { AlertFormType } from '../logic/alertFormLogic'
import { ForecastSimulationSection } from './ForecastSimulationSection'

describe('ForecastSimulationSection', () => {
    const breachAlert = (bounds: InsightsThresholdBounds): AlertFormType =>
        ({
            name: 'My alert',
            calculation_interval: AlertCalculationInterval.DAILY,
            condition: { type: AlertConditionType.ABSOLUTE_VALUE },
            threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds } },
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.FUTURE_BREACH,
                horizon: 7,
            },
        }) as unknown as AlertFormType

    const previewButton = (bounds: InsightsThresholdBounds): Element | null => {
        const { container } = render(
            <ForecastSimulationSection
                alertForm={breachAlert(bounds)}
                insightInterval="day"
                projectTimezone="UTC"
                forecastSimulationResultLoading={false}
                simulationDateFrom={null}
                onSimulateForecast={jest.fn()}
                onSetSimulationDateFrom={jest.fn()}
            />
        )
        return container.querySelector('[data-attr="alertForm-simulate-forecast"]')
    }

    it.each([
        ['no bound is set yet', {}],
        ['the bounds are inverted, so every point would read as a breach', { lower: 100, upper: 10 }],
    ] as const)('blocks the preview when %s', (_name, bounds) => {
        expect(previewButton(bounds)?.getAttribute('aria-disabled')).toBe('true')
    })

    it.each([
        ['one bound', { upper: 100 }],
        ['a valid range', { lower: 10, upper: 100 }],
    ] as const)('allows the preview with %s', (_name, bounds) => {
        expect(previewButton(bounds)?.getAttribute('aria-disabled')).toBe('false')
    })
})
