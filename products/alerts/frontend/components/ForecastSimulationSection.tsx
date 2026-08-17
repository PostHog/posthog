import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { ForecastConditionType } from '~/queries/schema/schema-general'

import { ForecastSimulateResponseApi } from 'products/alerts/frontend/generated/api.schemas'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { ForecastPreview } from 'products/alerts/frontend/views/ForecastPreview'

import { getSimulationRangeOptions } from './editAlertModalUtils'

interface ForecastSimulationSectionProps {
    alertForm: AlertFormType
    forecastSimulationResult: ForecastSimulateResponseApi | null
    forecastSimulationResultLoading: boolean
    simulationDateFrom: string | null
    onSimulateForecast: () => void
    onSetSimulationDateFrom: (value: string) => void
}

export function ForecastSimulationSection({
    alertForm,
    forecastSimulationResult,
    forecastSimulationResultLoading,
    simulationDateFrom,
    onSimulateForecast,
    onSetSimulationDateFrom,
}: ForecastSimulationSectionProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <div className="flex gap-2 items-center">
                <h4 className="m-0">Simulation</h4>
                <LemonSelect
                    size="small"
                    data-attr="alertForm-simulate-forecast-range"
                    value={simulationDateFrom ?? getDefaultSimulationRange(alertForm.calculation_interval)}
                    onChange={onSetSimulationDateFrom}
                    options={getSimulationRangeOptions(alertForm.calculation_interval)}
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="alertForm-simulate-forecast"
                    onClick={onSimulateForecast}
                    loading={forecastSimulationResultLoading}
                    tooltip="Run the forecast on historical data to preview the predicted trend and its expected range"
                >
                    Simulate
                </LemonButton>
            </div>
            {forecastSimulationResult && (
                <ForecastPreview
                    result={forecastSimulationResult}
                    thresholdBounds={
                        alertForm.forecast_config?.condition === ForecastConditionType.FUTURE_BREACH
                            ? (alertForm.threshold.configuration.bounds ?? null)
                            : null
                    }
                />
            )}
        </div>
    )
}
