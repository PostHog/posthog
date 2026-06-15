import { useValues } from 'kea'

import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'

import type { DashboardWidgetHeaderEyebrowProps } from '../../components/WidgetCard/WidgetCardHeader'
import { sessionReplayWidgetSavedFiltersLogic } from './sessionReplayWidgetSavedFiltersLogic'

// When a saved filter drives the widget it overrides the date range, so the eyebrow shows the
// saved filter's name instead of a now-misleading range.
export function SessionReplayWidgetHeaderEyebrow({
    config,
    widgetTypeLabel,
    showWidgetType,
    dateText,
}: DashboardWidgetHeaderEyebrowProps): JSX.Element {
    const rawSavedFilterId = config.savedFilterId
    const savedFilterId = typeof rawSavedFilterId === 'string' && rawSavedFilterId.length > 0 ? rawSavedFilterId : null
    const { savedFilterLabelById } = useValues(sessionReplayWidgetSavedFiltersLogic)

    if (savedFilterId) {
        const savedFilterName = savedFilterLabelById[savedFilterId]
        return (
            <CardTopHeadingRow
                typeLabel={widgetTypeLabel}
                showTypeLabel={showWidgetType}
                dateText={savedFilterName ?? 'Saved filter'}
            />
        )
    }

    return <CardTopHeadingRow typeLabel={widgetTypeLabel} showTypeLabel={showWidgetType} dateText={dateText} />
}
