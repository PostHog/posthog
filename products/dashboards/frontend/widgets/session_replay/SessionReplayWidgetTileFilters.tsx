import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
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
        () => [NO_SAVED_FILTER_OPTION, ...savedFilterOptions],
        [savedFilterOptions]
    )
    const savedFilterLabel = useMemo(
        () => savedFilterOptions.find((option) => option.value === savedFilterId)?.label ?? savedFilterId,
        [savedFilterOptions, savedFilterId]
    )
    // When the project has no saved filters yet, prompt the user to create one in session replay
    // rather than showing an empty picker.
    const showSavedFilterPrompt = !savedFiltersLoading && savedFilterOptions.length === 0 && !hasSavedFilter

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
            {showSavedFilterPrompt ? (
                <span className="text-xs text-muted" data-attr="session-replay-widget-no-saved-filters">
                    No saved filters yet —{' '}
                    <Link to={urls.replay()} target="_blank">
                        create one in session replay
                    </Link>
                </span>
            ) : (
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
            )}
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
