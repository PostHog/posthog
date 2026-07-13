import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconExternal } from '@posthog/icons'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { LemonSelect, type LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

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

const NONE_VALUE = '__none__'
const CREATE_SAVED_FILTER_VALUE = '__create_saved_filter__'
const CREATE_COLLECTION_VALUE = '__create_collection__'

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
    const collectionId = parsed.collectionId ?? null
    const hasSavedFilter = !!savedFilterId
    const hasCollection = !!collectionId
    // A saved filter owns the date range and property filters. Otherwise both controls apply — including on
    // top of a collection, so you can scope to a collection and still narrow it by date and properties.
    const showDateRange = !hasSavedFilter
    const showPropertyFilters = !hasSavedFilter

    const { quickFilters: projectFilterDefinitions } = useValues(
        quickFiltersLogic({ context: filterDefinitionsContext })
    )
    const {
        savedFilterOptions,
        collectionOptions,
        savedFiltersLoading,
        collectionsLoading,
        savedFilterLabelById,
        collectionLabelById,
    } = useValues(sessionReplayWidgetSavedFiltersLogic)
    const filterDefinitions = useMemo(
        () => projectFilterDefinitions.filter(isAllowed),
        [projectFilterDefinitions, isAllowed]
    )

    const collectionSelectOptions = useMemo<LemonSelectOptionLeaf<string>[]>(
        () => [
            { value: NONE_VALUE, label: 'No collection' },
            ...collectionOptions,
            // Always offer a shortcut to create a new collection in session replay.
            {
                value: CREATE_COLLECTION_VALUE,
                label: 'Create a collection',
                sideIcon: <IconExternal className="size-3.5" />,
            },
        ],
        [collectionOptions]
    )
    const savedFilterSelectOptions = useMemo<LemonSelectOptionLeaf<string>[]>(
        () => [
            { value: NONE_VALUE, label: 'No saved filter' },
            ...savedFilterOptions,
            // Always offer a shortcut to create a new saved filter in session replay.
            {
                value: CREATE_SAVED_FILTER_VALUE,
                label: 'Create a saved filter',
                sideIcon: <IconExternal className="size-3.5" />,
            },
        ],
        [savedFilterOptions]
    )

    const savedFilterLabel = savedFilterId ? (savedFilterLabelById[savedFilterId] ?? savedFilterId) : null
    const collectionLabel = collectionId ? (collectionLabelById[collectionId] ?? collectionId) : null

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

    const applyCollection = async (value: string | null): Promise<void> => {
        // The "create" item is a navigation shortcut to the collections tab, not a persisted value.
        if (value === CREATE_COLLECTION_VALUE) {
            window.open(urls.replay(ReplayTabs.Playlists), '_blank', 'noopener,noreferrer')
            return
        }
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, {
            collectionId: value && value !== NONE_VALUE ? value : null,
        })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    const applySavedFilter = async (value: string | null): Promise<void> => {
        // The "create" item is a navigation shortcut, not a persisted value.
        if (value === CREATE_SAVED_FILTER_VALUE) {
            window.open(urls.replay(), '_blank', 'noopener,noreferrer')
            return
        }
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, {
            savedFilterId: value && value !== NONE_VALUE ? value : null,
        })
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
                {hasCollection ? <span className="text-sm text-muted">Collection: {collectionLabel}</span> : null}
                {hasSavedFilter ? <span className="text-sm text-muted">Filter: {savedFilterLabel}</span> : null}
                {showDateRange ? <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} /> : null}
                {showPropertyFilters && filterDefinitions.length > 0 ? (
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
                value={collectionId ?? NONE_VALUE}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                loading={collectionsLoading}
                options={collectionSelectOptions}
                placeholder="Collection"
                onChange={(value) => void applyCollection(value)}
            />
            <LemonSelect
                size="small"
                value={savedFilterId ?? NONE_VALUE}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                loading={savedFiltersLoading}
                options={savedFilterSelectOptions}
                placeholder="Saved filter"
                onChange={(value) => void applySavedFilter(value)}
            />
            {showDateRange ? (
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
            ) : null}
            {showPropertyFilters && filterDefinitions.length > 0 ? (
                <WidgetPropertyFiltersSection
                    filterDefinitions={filterDefinitions}
                    widgetFilters={widgetFilters}
                    onWidgetFiltersChange={applyWidgetFilters}
                />
            ) : null}
        </WidgetTileFiltersBar>
    )
}
