import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import {
    WidgetDateRangeReadOnlyValue,
    WidgetTileFilterReadOnlyLabel,
    WidgetTileFiltersBar,
} from '../widgetTileFiltersReadOnly'
import {
    WORKFLOWS_WIDGET_DEFAULT_DATE_FROM,
    WORKFLOWS_WIDGET_STATUS_OPTIONS,
    WORKFLOWS_WIDGET_TYPE_OPTIONS,
    parseWorkflowsWidgetConfig,
    patchWorkflowsWidgetFilterFields,
} from './workflowsWidgetConfigValidation'

export function WorkflowsWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const parsed = parseWorkflowsWidgetConfig(config)
    const status = parsed.status ?? 'active'
    const workflowType = parsed.workflowType ?? 'all'
    const dateFrom = (parsed.dateRange?.date_from ?? WORKFLOWS_WIDGET_DEFAULT_DATE_FROM) as WidgetDateFromValue
    const { getLatestConfig, persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig, config)
    const canUpdate = !!onUpdateConfig && !disabledReason

    const applyPatch = (patch: Parameters<typeof patchWorkflowsWidgetFilterFields>[1]): void => {
        void persistConfigNow(patchWorkflowsWidgetFilterFields(getLatestConfig(), patch))
    }

    if (!onUpdateConfig) {
        const statusLabel = WORKFLOWS_WIDGET_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
        const typeLabel =
            WORKFLOWS_WIDGET_TYPE_OPTIONS.find((option) => option.value === workflowType)?.label ?? workflowType
        return (
            <WidgetTileFiltersBar dataAttr="workflows-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
                <WidgetTileFilterReadOnlyLabel name="Status" value={statusLabel} />
                <WidgetTileFilterReadOnlyLabel name="Type" value={typeLabel} />
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="workflows-widget-tile-filters">
            <LemonSelect
                size="small"
                value={dateFrom}
                disabled={!canUpdate}
                disabledReason={disabledReason ?? undefined}
                options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        applyPatch({ dateFrom: value })
                    }
                }}
            />
            <LemonSelect
                size="small"
                value={status}
                disabled={!canUpdate}
                disabledReason={disabledReason ?? undefined}
                options={WORKFLOWS_WIDGET_STATUS_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        applyPatch({ status: value })
                    }
                }}
            />
            <LemonSelect
                size="small"
                value={workflowType}
                disabled={!canUpdate}
                disabledReason={disabledReason ?? undefined}
                options={WORKFLOWS_WIDGET_TYPE_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        applyPatch({ workflowType: value })
                    }
                }}
            />
        </WidgetTileFiltersBar>
    )
}
