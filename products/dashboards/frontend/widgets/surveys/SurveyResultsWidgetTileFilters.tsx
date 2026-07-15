import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import { surveyPickerLogic } from './surveyPickerLogic'
import { SurveyPickerSelect } from './SurveyPickerSelect'
import { parseSurveyResultsWidgetConfig, patchSurveyResultsWidgetConfig } from './surveysWidgetConfigValidation'

function SurveyResultsReadOnlyValue({ tileId, surveyId }: { tileId: number; surveyId: string }): JSX.Element {
    const { selectedSurvey } = useValues(
        surveyPickerLogic({ pickerKey: `results-tile-${tileId}`, ensureSurveyId: surveyId })
    )
    return (
        <WidgetTileFilterReadOnlyValue>
            <span className="text-secondary">Survey:</span>{' '}
            {selectedSurvey?.id === surveyId ? selectedSurvey.name : 'Selected survey'}
        </WidgetTileFilterReadOnlyValue>
    )
}

export function SurveyResultsWidgetTileFilters({
    tileId,
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const surveyId = parseSurveyResultsWidgetConfig(config).surveyId ?? null

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    // Reflect the pick immediately rather than waiting for the persist round-trip to update `config`.
    const [optimisticSurveyId, setOptimisticSurveyId] = useState<string | null | undefined>(undefined)
    const selectedSurveyId = optimisticSurveyId !== undefined ? optimisticSurveyId : surveyId

    const applySurveyId = async (value: string | null): Promise<void> => {
        setOptimisticSurveyId(value)
        const nextConfig = patchSurveyResultsWidgetConfig(configRef.current, value)
        configRef.current = nextConfig
        try {
            await persistConfigNow(nextConfig)
        } finally {
            // Only clear if a newer pick hasn't superseded this one.
            setOptimisticSurveyId((current) => (current === value ? undefined : current))
        }
    }

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="survey-results-widget-tile-filters-readonly">
                {surveyId != null ? (
                    <SurveyResultsReadOnlyValue tileId={tileId} surveyId={surveyId} />
                ) : (
                    <WidgetTileFilterReadOnlyValue>
                        <span className="text-secondary">Survey:</span> None selected
                    </WidgetTileFilterReadOnlyValue>
                )}
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="survey-results-widget-tile-filters">
            <div className="w-64 max-w-full">
                <SurveyPickerSelect
                    pickerKey={`results-tile-${tileId}`}
                    value={selectedSurveyId}
                    disabled={!!disabledReason}
                    fullWidth
                    onChange={(value) => {
                        void applySurveyId(value)
                    }}
                    onCreateNew={() =>
                        posthog.capture('dashboard widget create survey clicked', {
                            widget_type: 'survey_results',
                            tile_id: tileId,
                        })
                    }
                    dataAttr="survey-results-widget-tile-survey-select"
                />
            </div>
        </WidgetTileFiltersBar>
    )
}
