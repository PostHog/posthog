import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { forecastTargetDateError } from 'products/alerts/frontend/logic/forecastReach'

import { getSimulationRangeOptions } from './editAlertModalUtils'

interface ForecastSimulationSectionProps {
    alertForm: AlertFormType
    forecastSimulationResultLoading: boolean
    simulationDateFrom: string | null
    onSimulateForecast: () => void
    onSetSimulationDateFrom: (value: string) => void
}

/** Controls for the forecast simulation. The result renders in the editor's preview card rather
 *  than here, so the user sees one chart instead of a second one under the controls. */
export function ForecastSimulationSection({
    alertForm,
    forecastSimulationResultLoading,
    simulationDateFrom,
    onSimulateForecast,
    onSetSimulationDateFrom,
}: ForecastSimulationSectionProps): JSX.Element {
    // The endpoint rejects an out-of-range target, so block the request rather than spending a round
    // trip to surface an error the editor already knows about.
    const targetDateError = forecastTargetDateError(alertForm.forecast_config?.target_date, dayjs())
    return (
        <div className="flex gap-2 items-center">
            <div className="flex items-center gap-1.5">
                <h4 className="m-0">Simulation</h4>
                <Tooltip
                    title="Previews the forecast over past data. It does not change what the alert evaluates when it runs."
                    delayMs={0}
                >
                    <IconInfo className="text-muted size-3.5" />
                </Tooltip>
            </div>
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
                disabledReason={targetDateError ?? undefined}
                tooltip="Run the forecast on historical data to preview the predicted trend and its expected range"
            >
                Simulate
            </LemonButton>
        </div>
    )
}
