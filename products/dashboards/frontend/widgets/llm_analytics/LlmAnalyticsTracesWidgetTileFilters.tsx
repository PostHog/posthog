import { useRef } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetDateRangeReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
    parseLlmAnalyticsTracesWidgetConfig,
    patchLlmAnalyticsTracesWidgetFilterFields,
} from './llmAnalyticsTracesWidgetConfigValidation'

export type LlmAnalyticsTracesWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

export function LlmAnalyticsTracesWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: LlmAnalyticsTracesWidgetTileFiltersProps): JSX.Element {
    const parsed = parseLlmAnalyticsTracesWidgetConfig(config)
    const dateFrom = (parsed.dateRange?.date_from ?? LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM) as WidgetDateFromValue

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    const controlDisabledReason = disabledReason
    const canUpdate = !!onUpdateConfig && !controlDisabledReason

    const applyDateFrom = async (value: WidgetDateFromValue): Promise<void> => {
        const nextConfig = patchLlmAnalyticsTracesWidgetFilterFields(configRef.current, { dateFrom: value })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="llm-analytics-traces-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="llm-analytics-traces-widget-tile-filters">
            <LemonSelect
                size="small"
                value={dateFrom}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        void applyDateFrom(value)
                    }
                }}
            />
        </WidgetTileFiltersBar>
    )
}
