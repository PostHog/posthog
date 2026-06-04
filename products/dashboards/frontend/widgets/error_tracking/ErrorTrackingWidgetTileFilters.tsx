import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import type { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ErrorTrackingAssigneeSelectButton } from 'products/error_tracking/frontend/components/Assignee/ErrorTrackingAssigneeSelectButton'
import {
    ErrorTrackingStatusSelect,
    type ErrorTrackingStatusSelectValue,
} from 'products/error_tracking/frontend/components/IssueFilters/Status'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/configSchemas'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { WidgetPropertyFiltersSection } from '../WidgetPropertyFiltersSection'
import { errorTrackingWidgetFiltersSetup, useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import {
    ErrorTrackingAssigneeReadOnlyValue,
    ErrorTrackingStatusReadOnlyValue,
    isWidgetTileFiltersReadOnly,
    WidgetDateRangeReadOnlyValue,
    WidgetPropertyFiltersReadOnlyValues,
    WidgetTileFiltersBar,
} from '../widgetTileFiltersReadOnly'
import {
    patchErrorTrackingWidgetFilterFields,
    parseErrorTrackingWidgetConfig,
} from './errorTrackingWidgetConfigValidation'

export type ErrorTrackingWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

export function ErrorTrackingWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: ErrorTrackingWidgetTileFiltersProps): JSX.Element {
    const { context: filterDefinitionsContext, isAllowed } = errorTrackingWidgetFiltersSetup
    const parsed = parseErrorTrackingWidgetConfig(config)
    const dateFrom = (parsed.dateRange?.date_from ?? '-7d') as WidgetDateFromValue
    const status = (parsed.status ?? 'active') as ErrorTrackingStatusSelectValue
    const assignee = parsed.assignee ?? null
    const widgetFilters = parsed.widgetFilters ?? {}

    const { quickFilters: projectFilterDefinitions } = useValues(
        quickFiltersLogic({ context: filterDefinitionsContext })
    )
    const filterDefinitions = useMemo(
        () => projectFilterDefinitions.filter(isAllowed),
        [projectFilterDefinitions, isAllowed]
    )

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigDebounced, persistConfigNow, isPersisting } = useWidgetTileConfigPersist(onUpdateConfig)

    const controlDisabledReason = disabledReason ?? (isPersisting ? 'Updating…' : undefined)
    const canUpdate = !!onUpdateConfig && !controlDisabledReason
    const readOnly = isWidgetTileFiltersReadOnly(onUpdateConfig)

    const applyPatch = async (patch: Parameters<typeof patchErrorTrackingWidgetFilterFields>[1]): Promise<void> => {
        const nextConfig = patchErrorTrackingWidgetFilterFields(configRef.current, patch)
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    const applyWidgetFilters = (nextWidgetFilters: typeof widgetFilters): void => {
        const nextConfig = patchErrorTrackingWidgetFilterFields(configRef.current, { widgetFilters: nextWidgetFilters })
        const current = parseErrorTrackingWidgetConfig(configRef.current)
        if (equal(current.widgetFilters ?? {}, nextWidgetFilters)) {
            return
        }
        configRef.current = nextConfig
        persistConfigDebounced(nextConfig)
    }

    if (readOnly) {
        return (
            <WidgetTileFiltersBar dataAttr="error-tracking-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
                <ErrorTrackingStatusReadOnlyValue status={status} />
                <ErrorTrackingAssigneeReadOnlyValue assignee={assignee} />
                {filterDefinitions.length > 0 ? (
                    <WidgetPropertyFiltersReadOnlyValues
                        filterDefinitions={filterDefinitions}
                        widgetFilters={widgetFilters}
                    />
                ) : null}
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="error-tracking-widget-tile-filters">
            <LemonSelect
                size="small"
                value={dateFrom}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        void applyPatch({ dateFrom: value })
                    }
                }}
            />
            <ErrorTrackingStatusSelect
                value={status}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                onChange={(value) => {
                    void applyPatch({ status: value })
                }}
            />
            <ErrorTrackingAssigneeSelectButton
                assignee={assignee}
                onChange={(value: ErrorTrackingIssue['assignee']) => {
                    void applyPatch({ assignee: value ?? null })
                }}
            />
            {filterDefinitions.length > 0 ? (
                <WidgetPropertyFiltersSection
                    filterDefinitions={filterDefinitions}
                    widgetFilters={widgetFilters}
                    onWidgetFiltersChange={applyWidgetFilters}
                />
            ) : null}
        </WidgetTileFiltersBar>
    )
}
