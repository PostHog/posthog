import { useEffect } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { IntervalType } from '~/types'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { forecastTargetDateError, usableSimulationRanges } from 'products/alerts/frontend/logic/forecastReach'

import { getSimulationRangeOptions } from './editAlertModalUtils'

interface ForecastSimulationSectionProps {
    alertForm: AlertFormType
    insightInterval: IntervalType | null | undefined
    forecastSimulationResultLoading: boolean
    simulationDateFrom: string | null
    onSimulateForecast: () => void
    onSetSimulationDateFrom: (value: string) => void
}

export function ForecastSimulationSection({
    alertForm,
    insightInterval,
    forecastSimulationResultLoading,
    simulationDateFrom,
    onSimulateForecast,
    onSetSimulationDateFrom,
}: ForecastSimulationSectionProps): JSX.Element {
    const targetDateError = forecastTargetDateError(alertForm.forecast_config?.target_date, dayjs())
    const rangeOptions = usableSimulationRanges(
        getSimulationRangeOptions(alertForm.calculation_interval),
        insightInterval,
        alertForm.forecast_config?.condition
    )
    const selectedRange = simulationDateFrom ?? getDefaultSimulationRange(alertForm.calculation_interval)
    const range = rangeOptions.some((o) => o.value === selectedRange) ? selectedRange : rangeOptions[0].value
    useEffect(() => {
        if (range !== selectedRange) {
            onSetSimulationDateFrom(range)
        }
    }, [range, selectedRange, onSetSimulationDateFrom])
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
                value={range}
                onChange={onSetSimulationDateFrom}
                options={rangeOptions}
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
