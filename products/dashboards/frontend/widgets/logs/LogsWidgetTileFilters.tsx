import { useRef } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { SeverityLevelsFilter } from 'products/logs/frontend/components/LogsViewer/Filters/SeverityLevelsFilter'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'

import type { DateRange, LogMessage } from '~/queries/schema/schema-general'

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

export type LogsWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

const SORT_OPTIONS: { value: LogsOrderByValue; label: string }[] = [
    { value: 'latest', label: 'Newest first' },
    { value: 'earliest', label: 'Oldest first' },
]

const ALL_SEVERITY_LEVELS = 6

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

export function LogsWidgetTileFilters({ config, onUpdateConfig, disabledReason }: LogsWidgetTileFiltersProps): JSX.Element {
    const parsed = parseLogsWidgetConfig(config)
    const severityLevels = (parsed.severityLevels ?? []) as LogsSeverityLevel[]
    const serviceNames = parsed.serviceNames ?? []
    const orderBy = (parsed.orderBy ?? 'latest') as LogsOrderByValue
    const dateFrom = (parsed.dateRange?.date_from ?? LOGS_DEFAULT_DATE_FROM) as WidgetDateFromValue

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
    }): Promise<void> => {
        const nextConfig = patchLogsWidgetFilterFields(configRef.current, patch)
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    if (!canUpdate) {
        return (
            <WidgetTileFiltersBar dataAttr="logs-widget-tile-filters-readonly">
                <WidgetTileFilterReadOnlyValue>
                    <span className="text-secondary">Levels:</span> {severityReadOnlyLabel(severityLevels)}
                </WidgetTileFilterReadOnlyValue>
                <WidgetTileFilterReadOnlyValue>
                    <span className="text-secondary">Services:</span> {servicesReadOnlyLabel(serviceNames)}
                </WidgetTileFilterReadOnlyValue>
                <WidgetTileFilterReadOnlyValue>
                    {SORT_OPTIONS.find((option) => option.value === orderBy)?.label ?? orderBy}
                </WidgetTileFilterReadOnlyValue>
            </WidgetTileFiltersBar>
        )
    }

    const serviceDateRange: DateRange = { date_from: dateFrom, date_to: null }

    return (
        <WidgetTileFiltersBar dataAttr="logs-widget-tile-filters">
            <SeverityLevelsFilter
                value={severityLevels as LogMessage['severity_text'][]}
                onChange={(levels) => void applyPatch({ severityLevels: levels as LogsSeverityLevel[] })}
            />
            <ServiceFilter
                value={serviceNames}
                dateRange={serviceDateRange}
                onChange={(services) => void applyPatch({ serviceNames: services ?? [] })}
            />
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
