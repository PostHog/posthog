import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { dayjsNowInTimezone } from 'lib/dayjs'

import { ForecastConditionType, InsightsThresholdBounds } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import {
    hasInvertedThresholdBounds,
    INVERTED_THRESHOLD_BOUNDS_FORM_ERROR,
} from 'products/alerts/frontend/logic/alertFormSchema'
import { getSimulationRangeOptions } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import {
    forecastTargetDateError,
    forecastTargetValueError,
    resolveForecastSimulationRange,
    usableSimulationRanges,
} from 'products/alerts/frontend/logic/forecastReach'

/** Why an upcoming-breach forecast cannot be previewed yet, or null when it can. The form rejects
 * the same bound pairs on save, but that error only shows once the user has tried to save. */
function breachThresholdError(bounds: InsightsThresholdBounds | null | undefined): string | null {
    if (bounds?.lower == null && bounds?.upper == null) {
        return 'Set a less-than or more-than threshold first'
    }
    if (hasInvertedThresholdBounds(bounds)) {
        return INVERTED_THRESHOLD_BOUNDS_FORM_ERROR
    }
    return null
}

interface ForecastSimulationSectionProps {
    alertForm: AlertFormType
    insightInterval: IntervalType | null | undefined
    projectTimezone: string
    forecastSimulationResultLoading: boolean
    simulationDateFrom: string | null
    onSimulateForecast: () => void
    onSetSimulationDateFrom: (value: string) => void
}

export function ForecastSimulationSection({
    alertForm,
    insightInterval,
    projectTimezone,
    forecastSimulationResultLoading,
    simulationDateFrom,
    onSimulateForecast,
    onSetSimulationDateFrom,
}: ForecastSimulationSectionProps): JSX.Element {
    const forecastConfig = alertForm.forecast_config
    const targetDateError =
        forecastConfig?.condition === ForecastConditionType.TARGET_BY_DATE
            ? forecastTargetDateError(forecastConfig.target_date, dayjsNowInTimezone(projectTimezone), insightInterval)
            : null
    const targetValueError =
        forecastConfig?.condition === ForecastConditionType.TARGET_BY_DATE
            ? forecastTargetValueError(forecastConfig.target)
            : null
    const thresholdError =
        forecastConfig?.condition === ForecastConditionType.FUTURE_BREACH
            ? breachThresholdError(alertForm.threshold?.configuration?.bounds)
            : null
    const disabledReason = targetValueError ?? targetDateError ?? thresholdError ?? undefined
    const rangeOptions = usableSimulationRanges(
        getSimulationRangeOptions(alertForm.calculation_interval),
        insightInterval
    )
    const range = resolveForecastSimulationRange(simulationDateFrom, alertForm.calculation_interval, insightInterval)
    return (
        <div className="flex flex-wrap gap-2 items-center">
            <div className="flex items-center gap-1.5">
                <h4 className="m-0">Forecast preview</h4>
                <Tooltip
                    title="Runs the configured forecast over the selected history. It does not change what the alert evaluates."
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
                disabledReason={disabledReason}
                tooltip="Run the forecast on historical data to preview the point forecast and its uncertainty range"
            >
                Preview forecast
            </LemonButton>
        </div>
    )
}
