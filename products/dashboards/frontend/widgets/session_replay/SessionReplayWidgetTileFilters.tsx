import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconExternal } from '@posthog/icons'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { LemonSelect, type LemonSelectSection } from 'lib/lemon-ui/LemonSelect'
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

const NO_SOURCE_VALUE = '__no_source__'
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
    const collectionId = parsed.collectionId ?? null
    const activeSourceId = savedFilterId ?? collectionId ?? null
    const hasSource = !!activeSourceId

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
        sourceTypeById,
    } = useValues(sessionReplayWidgetSavedFiltersLogic)
    const filterDefinitions = useMemo(
        () => projectFilterDefinitions.filter(isAllowed),
        [projectFilterDefinitions, isAllowed]
    )

    const sourceSelectOptions = useMemo<LemonSelectSection<string>[]>(() => {
        const sections: LemonSelectSection<string>[] = [{ options: [{ value: NO_SOURCE_VALUE, label: 'No source' }] }]
        if (savedFilterOptions.length > 0) {
            sections.push({ title: 'Saved filters', options: savedFilterOptions })
        }
        if (collectionOptions.length > 0) {
            sections.push({ title: 'Collections', options: collectionOptions })
        }
        // Always offer a shortcut to create a new saved filter in session replay.
        sections.push({
            options: [
                {
                    value: CREATE_SAVED_FILTER_VALUE,
                    label: 'Create a saved filter',
                    sideIcon: <IconExternal className="size-3.5" />,
                },
            ],
        })
        return sections
    }, [savedFilterOptions, collectionOptions])

    const sourceLabel = activeSourceId
        ? (savedFilterLabelById[activeSourceId] ?? collectionLabelById[activeSourceId] ?? activeSourceId)
        : null

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

    const applySource = async (value: string): Promise<void> => {
        // The "create" item is a navigation shortcut, not a persisted value.
        if (value === CREATE_SAVED_FILTER_VALUE) {
            window.open(urls.replay(), '_blank', 'noopener,noreferrer')
            return
        }
        const nextSourceId = value === NO_SOURCE_VALUE ? null : value
        // A source short_id is either a saved filter or a collection; route it to the matching config field.
        const patch =
            nextSourceId !== null && sourceTypeById[nextSourceId] === 'collection'
                ? { collectionId: nextSourceId }
                : { savedFilterId: nextSourceId }
        const nextConfig = patchSessionReplayWidgetFilterFields(configRef.current, patch)
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
                {hasSource ? (
                    <span className="text-sm text-muted">Source: {sourceLabel}</span>
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
                value={activeSourceId ?? NO_SOURCE_VALUE}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                loading={savedFiltersLoading || collectionsLoading}
                options={sourceSelectOptions}
                placeholder="Saved filter or collection"
                onChange={(value) => void applySource(value ?? NO_SOURCE_VALUE)}
            />
            {!hasSource ? (
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
