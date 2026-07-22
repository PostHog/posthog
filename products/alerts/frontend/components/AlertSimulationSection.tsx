import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { getDefaultSimulationRange } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { AlertSimulationResult } from 'products/alerts/frontend/types'
import { SimulationSummary } from 'products/alerts/frontend/views/SimulationSummary'

import { getSimulationRangeOptions } from './editAlertModalUtils'

interface AlertSimulationSectionProps {
    alertForm: AlertFormType
    simulationResult: AlertSimulationResult | null
    simulationResultLoading: boolean
    simulationDateFrom: string | null
    onSimulateAlert: () => void
    onSetSimulationDateFrom: (value: string) => void
}

export function AlertSimulationSection({
    alertForm,
    simulationResult,
    simulationResultLoading,
    simulationDateFrom,
    onSimulateAlert,
    onSetSimulationDateFrom,
}: AlertSimulationSectionProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <div className="flex gap-2 items-center">
                <h4 className="m-0">Simulation</h4>
                <LemonSelect
                    size="small"
                    data-attr="alertForm-simulate-range"
                    value={simulationDateFrom ?? getDefaultSimulationRange(alertForm.calculation_interval)}
                    onChange={onSetSimulationDateFrom}
                    options={getSimulationRangeOptions(alertForm.calculation_interval)}
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="alertForm-simulate"
                    onClick={onSimulateAlert}
                    loading={simulationResultLoading}
                    tooltip="Run the detector on historical data to preview which points would be flagged as anomalies"
                >
                    Simulate
                </LemonButton>
            </div>
            {simulationResult && alertForm.detector_config && (
                <SimulationSummary result={simulationResult} detectorConfig={alertForm.detector_config} />
            )}
        </div>
    )
}
