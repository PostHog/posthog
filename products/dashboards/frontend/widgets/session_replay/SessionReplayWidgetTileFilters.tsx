import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { urls } from 'scenes/urls'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { WidgetPropertyFiltersSection } from '../WidgetPropertyFiltersSection'
import { getWidgetTileFiltersSetup, useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import {
    WidgetDateRangeReadOnlyValue,
    WidgetPropertyFiltersReadOnlyValues,
    WidgetTileFiltersBar,
} from '../widgetTileFiltersReadOnly'
import {
    parseSessionReplayWidgetConfig,
    patchSessionReplayWidgetFilterFields,
} from './sessionReplayWidgetConfigValidation'
import { sessionReplayWidgetSavedFiltersLogic } from './sessionReplayWidgetSavedFiltersLogic'

export type SessionReplayWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

const NO_SAVED_FILTER_OPTION = { value: null as string | null, label: 'No saved filter' }
// Sentinel value: selecting it navigates to session replay to create a filter rather than persisting.
const CREATE_SAVED_FILTER_VALUE = '__create_saved_filter__'

export function SessionReplayWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: SessionReplayWidgetTileFiltersProps): JSX.Element {
    const { context: filterDefinitionsContext, isAllowed } = getWidgetTileFiltersSetup('session_replay_list')
    const parsed = parseSessionReplayWidgetConfig(config)
    const dateFrom = (parsed.dateRange?.date_from ?? '-7d') as WidgetDateFromValue
    const widgetFilters = parsed.widgetFilters ?? {}
    const savedFilterId = parsed.savedFilterId ?? null
    const hasSavedFilter = !!savedFilterId

    const { quickFilters: projectFilterDefinitions } = useValues(
        quickFiltersLogic({ context: filterDefinitionsContext })
    )
    const { savedFilterOptions, savedFiltersLoading } = useValues(sessionReplayWidgetSavedFiltersLogic)
    const filterDefinitions = useMemo(
        () => projectFilterDefinitions.filter(isAllowed),
        [projectFilterDefinitions, isAllowed]
    )

    const savedFilterSelectOptions = useMemo(
        () => [
            NO_SAVED_FILTER_OPTION,
            ...savedFilterOptions,
            // Always offer a shortcut to create a new saved filter in session replay.
            {
                value: CREATE_SAVED_FILTER_VALUE,
                label: 'Create a saved filter',
                sideIcon: <IconOpenInNew />,
            },
        ],
        [savedFilterOptions]
    )
    const savedFilterLabel = useMemo(
        () => savedFilterOptions.find((option) => option.value === savedFilterId)?.label ?? savedFilterId,
        [savedFilterOptions, savedFilterId]
    )

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigDebounced, persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    const controlDisabledReason = disabledReason
    const canUpdate = !!onUpdateConfig && !controlDisabledReason

    const applyDateFrom = async (value: WidgetDateFromValue): Promise<void> => {
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, { dateFrom: value })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    const applySavedFilter = async (value: string | null): Promise<void> => {
        // The "create" item is a navigation shortcut, not a persisted value.
        if (value === CREATE_SAVED_FILTER_VALUE) {
            window.open(urls.replay(), '_blank', 'noopener,noreferrer')
            return
        }
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, { savedFilterId: value })
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

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="session-replay-widget-tile-filters-readonly">
                {hasSavedFilter ? (
                    <span className="text-sm text-muted">Saved filter: {savedFilterLabel}</span>
                ) : (
                    <>
                        <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
                        {filterDefinitions.length > 0 ? (
                            <WidgetPropertyFiltersReadOnlyValues
                                filterDefinitions={filterDefinitions}
                                widgetFilters={widgetFilters}
                            />
                        ) : null}
                    </>
                )}
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="session-replay-widget-tile-filters">
            <LemonSelect
                size="small"
                value={savedFilterId}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                loading={savedFiltersLoading}
                options={savedFilterSelectOptions}
                placeholder="Saved filter"
                onChange={(value) => void applySavedFilter(value ?? null)}
            />
            {!hasSavedFilter ? (
                <>
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
                </>
            ) : null}
        </WidgetTileFiltersBar>
    )
}
