import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import { experimentPickerLogic } from './experimentPickerLogic'
import { ExperimentPickerSelect } from './ExperimentPickerSelect'
import {
    parseExperimentResultsWidgetConfig,
    patchExperimentResultsWidgetConfig,
} from './experimentsWidgetConfigValidation'

function ExperimentResultsReadOnlyValue({
    tileId,
    experimentId,
}: {
    tileId: number
    experimentId: number
}): JSX.Element {
    const logic = experimentPickerLogic({ pickerKey: `results-tile-${tileId}` })
    const { selectedExperiment } = useValues(logic)
    const { ensureSelectedLoaded } = useActions(logic)
    useEffect(() => {
        ensureSelectedLoaded(experimentId)
    }, [experimentId, ensureSelectedLoaded])
    return (
        <WidgetTileFilterReadOnlyValue>
            <span className="text-secondary">Experiment:</span>{' '}
            {selectedExperiment?.id === experimentId ? selectedExperiment.name : `#${experimentId}`}
        </WidgetTileFilterReadOnlyValue>
    )
}

export function ExperimentResultsWidgetTileFilters({
    tileId,
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const parsed = parseExperimentResultsWidgetConfig(config)
    const experimentId = parsed.experimentId ?? null

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    const applyExperimentId = async (value: number | null): Promise<void> => {
        const nextConfig = patchExperimentResultsWidgetConfig(configRef.current, value)
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="experiment-results-widget-tile-filters-readonly">
                {experimentId != null ? (
                    <ExperimentResultsReadOnlyValue tileId={tileId} experimentId={experimentId} />
                ) : (
                    <WidgetTileFilterReadOnlyValue>
                        <span className="text-secondary">Experiment:</span> None selected
                    </WidgetTileFilterReadOnlyValue>
                )}
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="experiment-results-widget-tile-filters">
            <div className="w-64 max-w-full">
                <ExperimentPickerSelect
                    pickerKey={`results-tile-${tileId}`}
                    value={experimentId}
                    disabled={!!disabledReason}
                    fullWidth
                    onChange={(value) => {
                        void applyExperimentId(value)
                    }}
                    dataAttr="experiment-results-widget-tile-experiment-select"
                />
            </div>
        </WidgetTileFiltersBar>
    )
}
