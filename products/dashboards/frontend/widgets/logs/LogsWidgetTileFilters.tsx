import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconExternal } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { DateRange, LogMessage } from '~/queries/schema/schema-general'

import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { SeverityLevelsFilter } from 'products/logs/frontend/components/LogsViewer/Filters/SeverityLevelsFilter'

import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    LOGS_DEFAULT_DATE_FROM,
    parseLogsWidgetConfig,
    patchLogsWidgetFilterFields,
    type LogsOrderByValue,
    type LogsSeverityLevel,
} from './logsWidgetConfigValidation'
import { logsWidgetSavedViewsLogic } from './logsWidgetSavedViewsLogic'

export type LogsWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

const SORT_OPTIONS: { value: LogsOrderByValue; label: string }[] = [
    { value: 'latest', label: 'Newest first' },
    { value: 'earliest', label: 'Oldest first' },
]

const ALL_SEVERITY_LEVELS = 6

const NO_SAVED_VIEW_OPTION = { value: null as string | null, label: 'No saved view' }
const CREATE_SAVED_VIEW_VALUE = '__create_saved_view__'

function severityReadOnlyLabel(levels: LogsSeverityLevel[]): string {
    if (levels.length === 0 || levels.length === ALL_SEVERITY_LEVELS) {
        return 'All levels'
    }
    return levels.join(', ')
}

function servicesReadOnlyLabel(services: string[]): string {
    if (services.length === 0) {
        return 'All services'
    }
    if (services.length === 1) {
        return services[0]
    }
    return `${services.length} services`
}

export function LogsWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: LogsWidgetTileFiltersProps): JSX.Element {
    const parsed = parseLogsWidgetConfig(config)
    const severityLevels = (parsed.severityLevels ?? []) as LogsSeverityLevel[]
    const serviceNames = parsed.serviceNames ?? []
    const orderBy = (parsed.orderBy ?? 'latest') as LogsOrderByValue
    const dateFrom = (parsed.dateRange?.date_from ?? LOGS_DEFAULT_DATE_FROM) as WidgetDateFromValue
    const savedViewId = parsed.savedViewId ?? null
    const hasSavedView = !!savedViewId

    const { featureFlags } = useValues(featureFlagLogic)
    const savedViewsEnabled = !!featureFlags[FEATURE_FLAGS.LOGS_SAVED_VIEWS]
    // Keep the picker reachable when a view is already persisted, even if the flag is later turned
    // off — otherwise the tile would be stuck on that view with no way to clear it.
    const showSavedViewPicker = savedViewsEnabled || hasSavedView
    const { savedViewOptions, savedViewsLoading, savedViewLabelById } = useValues(logsWidgetSavedViewsLogic)
    const { ensureSavedViewsLoaded } = useActions(logsWidgetSavedViewsLogic)

    useEffect(() => {
        if (showSavedViewPicker) {
            ensureSavedViewsLoaded()
        }
    }, [showSavedViewPicker, ensureSavedViewsLoaded])

    const savedViewSelectOptions = useMemo(
        () => [
            NO_SAVED_VIEW_OPTION,
            ...savedViewOptions,
            {
                value: CREATE_SAVED_VIEW_VALUE,
                label: 'Create a saved view',
                sideIcon: <IconExternal className="size-3.5" />,
            },
        ],
        [savedViewOptions]
    )
    const savedViewLabel = savedViewId ? (savedViewLabelById[savedViewId] ?? savedViewId) : savedViewId

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    // Severity and service pickers can't render a disabled state, so when editing is unavailable
    // (view-only dashboard, or no edit permission) show the read-only summary instead of dead controls.
    const canUpdate = !!onUpdateConfig && !disabledReason

    const applyPatch = async (patch: {
        severityLevels?: LogsSeverityLevel[]
        serviceNames?: string[]
        orderBy?: LogsOrderByValue
        savedViewId?: string | null
    }): Promise<void> => {
        const nextConfig = patchLogsWidgetFilterFields(configRef.current, patch)
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    const applySavedView = async (value: string | null): Promise<void> => {
        // The "create" item is a navigation shortcut, not a persisted value.
        if (value === CREATE_SAVED_VIEW_VALUE) {
            window.open(urls.logs(), '_blank', 'noopener,noreferrer')
            return
        }
        await applyPatch({ savedViewId: value })
    }

    if (!canUpdate) {
        return (
            <WidgetTileFiltersBar dataAttr="logs-widget-tile-filters-readonly">
                {hasSavedView ? (
                    <WidgetTileFilterReadOnlyValue>
                        <span className="text-secondary">Saved view:</span> {savedViewLabel}
                    </WidgetTileFilterReadOnlyValue>
                ) : (
                    <>
                        <WidgetTileFilterReadOnlyValue>
                            <span className="text-secondary">Levels:</span> {severityReadOnlyLabel(severityLevels)}
                        </WidgetTileFilterReadOnlyValue>
                        <WidgetTileFilterReadOnlyValue>
                            <span className="text-secondary">Services:</span> {servicesReadOnlyLabel(serviceNames)}
                        </WidgetTileFilterReadOnlyValue>
                    </>
                )}
                <WidgetTileFilterReadOnlyValue>
                    {SORT_OPTIONS.find((option) => option.value === orderBy)?.label ?? orderBy}
                </WidgetTileFilterReadOnlyValue>
            </WidgetTileFiltersBar>
        )
    }

    const serviceDateRange: DateRange = { date_from: dateFrom, date_to: null }

    return (
        <WidgetTileFiltersBar dataAttr="logs-widget-tile-filters">
            {showSavedViewPicker ? (
                <LemonSelect
                    size="small"
                    value={savedViewId}
                    loading={savedViewsLoading}
                    options={savedViewSelectOptions}
                    placeholder="Saved view"
                    onChange={(value) => void applySavedView(value ?? null)}
                />
            ) : null}
            {!hasSavedView ? (
                <>
                    <SeverityLevelsFilter
                        value={severityLevels as LogMessage['severity_text'][]}
                        onChange={(levels) => void applyPatch({ severityLevels: levels as LogsSeverityLevel[] })}
                    />
                    <ServiceFilter
                        value={serviceNames}
                        dateRange={serviceDateRange}
                        onChange={(services) => void applyPatch({ serviceNames: services ?? [] })}
                    />
                </>
            ) : null}
            <LemonSelect
                size="small"
                value={orderBy}
                options={SORT_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        void applyPatch({ orderBy: value })
                    }
                }}
            />
        </WidgetTileFiltersBar>
    )
}
