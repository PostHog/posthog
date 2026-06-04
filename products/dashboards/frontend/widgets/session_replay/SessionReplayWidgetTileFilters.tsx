import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/configSchemas'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import {
    getAllowedWidgetFilterDefinitions,
    sessionReplayWidgetFiltersSetup,
    useWidgetTileConfigPersist,
} from '../widgetFilters'
import { WidgetPropertyFiltersSection } from '../WidgetPropertyFiltersSection'
import {
    isWidgetTileFiltersReadOnly,
    WidgetDateRangeReadOnlyValue,
    WidgetPropertyFiltersReadOnlyValues,
    WidgetTileFiltersBar,
} from '../widgetTileFiltersReadOnly'
import {
    patchSessionReplayWidgetFilterFields,
    parseSessionReplayWidgetConfig,
} from './sessionReplayWidgetConfigValidation'

export type SessionReplayWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

export function SessionReplayWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: SessionReplayWidgetTileFiltersProps): JSX.Element {
    const { context: filterDefinitionsContext, isAllowed } = sessionReplayWidgetFiltersSetup
    const parsed = parseSessionReplayWidgetConfig(config)
    const dateFrom = (parsed.dateRange?.date_from ?? '-7d') as WidgetDateFromValue
    const widgetFilters = parsed.widgetFilters ?? {}

    const { quickFilters } = useValues(quickFiltersLogic({ context: filterDefinitionsContext }))
    const filterDefinitions = useMemo(
        () => getAllowedWidgetFilterDefinitions(quickFilters, isAllowed),
        [quickFilters, isAllowed]
    )

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigDebounced, persistConfigNow, isPersisting } = useWidgetTileConfigPersist(onUpdateConfig)

    const controlDisabledReason = disabledReason ?? (isPersisting ? 'Updating…' : undefined)
    const canUpdate = !!onUpdateConfig && !controlDisabledReason
    const readOnly = isWidgetTileFiltersReadOnly(onUpdateConfig)

    const applyDateFrom = async (value: WidgetDateFromValue): Promise<void> => {
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, { dateFrom: value })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    const applyWidgetFilters = (nextWidgetFilters: typeof widgetFilters): void => {
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, { widgetFilters: nextWidgetFilters })
        const current = parseSessionReplayWidgetConfig(configRef.current)
        if (equal(current.widgetFilters ?? {}, nextWidgetFilters)) {
            return
        }
        configRef.current = nextConfig
        persistConfigDebounced(nextConfig)
    }

    if (readOnly) {
        return (
            <WidgetTileFiltersBar dataAttr="session-replay-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
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
        <WidgetTileFiltersBar dataAttr="session-replay-widget-tile-filters">
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
