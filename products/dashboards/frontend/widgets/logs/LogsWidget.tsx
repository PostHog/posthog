import { combineUrl } from 'kea-router'

import { HedgehogMagnifyingGlass } from '@posthog/brand/hoggies'

import { getLocalTimeZone } from 'lib/utils/timezones'
import { urls } from 'scenes/urls'

import {
    WIDGET_LIST_COUNT_LOGS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseLogsWidgetConfig } from './logsWidgetConfigValidation'
import { LogsWidgetRow, LogsWidgetRowSkeleton, type LogsWidgetLogLine } from './LogsWidgetRow'

export type LogsWidgetResult = {
    results?: LogsWidgetLogLine[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

/** 'local' renders in the viewer's own timezone; 'UTC' (default) renders the same for everyone. */
function resolveDisplayTimezone(timezone: string | null | undefined): string {
    if (timezone === 'local') {
        return getLocalTimeZone()
    }
    return 'UTC'
}

type LogsDeepLinkParams = {
    dateFrom: string | null | undefined
    orderBy: string | null | undefined
    limit: number | null | undefined
    severityLevels: string[]
    serviceNames: string[]
    hasSavedView: boolean
}

/** Deep-link that opens this log on the logs page (new tab), reproducing the tile's filtered view.
 *
 * Forwarding the tile's filters + orderBy + a matching `initialLogsLimit` makes the logs page's first
 * page equal the tile's visible rows, so the linked log is loaded and `linkToLogId` can open it. A
 * saved-view tile can't replay the view's filters (or its date range) client-side, so it links by id
 * only and lets the logs page use its own range — forwarding the tile's `-1h` default would likely
 * exclude the clicked log. */
function buildLogHref(line: LogsWidgetLogLine, params: LogsDeepLinkParams): string {
    return combineUrl(urls.logs(), {
        activeTab: 'viewer',
        linkToLogId: line.uuid,
        ...(params.hasSavedView ? {} : { dateRange: { date_from: params.dateFrom ?? null, date_to: null } }),
        ...(params.orderBy ? { orderBy: params.orderBy } : {}),
        ...(params.limit ? { initialLogsLimit: params.limit } : {}),
        ...(!params.hasSavedView && params.severityLevels.length ? { severityLevels: params.severityLevels } : {}),
        ...(!params.hasSavedView && params.serviceNames.length ? { serviceNames: params.serviceNames } : {}),
    }).url
}

export function LogsWidget({ result, loading, config }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as LogsWidgetResult | null | undefined
    const logLines = payload?.results ?? []

    const parsedConfig = parseLogsWidgetConfig(config)
    const wrapLines = parsedConfig.wrapLines ?? false
    const displayTimezone = resolveDisplayTimezone(parsedConfig.timezone)
    const deepLinkParams: LogsDeepLinkParams = {
        dateFrom: parsedConfig.dateRange?.date_from,
        orderBy: parsedConfig.orderBy,
        limit: parsedConfig.limit,
        severityLevels: parsedConfig.severityLevels ?? [],
        serviceNames: parsedConfig.serviceNames ?? [],
        hasSavedView: !!parsedConfig.savedViewId,
    }

    if (loading) {
        return (
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {Array.from({ length: 6 }, (_, index) => (
                        <LogsWidgetRowSkeleton key={index} />
                    ))}
                </div>
            </WidgetCardContent>
        )
    }

    if (logLines.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="logs-widget-empty-state"
                    >
                        <HedgehogMagnifyingGlass className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No logs found</p>
                        <p className="m-0 text-sm text-muted">
                            No logs matched your severity and service filters for this date range.
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {logLines.map((line) => (
                        <LogsWidgetRow
                            key={line.uuid}
                            line={line}
                            wrapLines={wrapLines}
                            displayTimezone={displayTimezone}
                            href={buildLogHref(line, deepLinkParams)}
                        />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={logLines.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_LOGS}
                    hasMore={payload?.hasMore}
                    dataAttr="logs-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
