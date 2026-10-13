import posthog from 'posthog-js'
import { Fragment } from 'react'

import {
    describeDescriptionChange,
    describeTagChanges,
} from 'lib/components/ActivityLog/activityDescriptions/changeDescriptions'
import { describeChangeMappings } from 'lib/components/ActivityLog/activityDescriptions/describeChangeMappings'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
    detectBoolean,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { Link } from 'lib/lemon-ui/Link'
import { areObjectValuesEmpty } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { HogQLQuery, InsightQueryNode, QuerySchema } from '~/queries/schema/schema-general'
import {
    isDataTableNodeWithHogQLQuery,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightQueryNode,
    isInsightVizNode,
} from '~/queries/utils'
import { FilterType, InsightModel, InsightShortId } from '~/types'

const nameOrLinkToInsight = (short_id?: InsightShortId | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return short_id ? <Link to={urls.insightView(short_id)}>{displayName}</Link> : displayName
}

interface TileStyleDashboardLink {
    insight: { id: number }
    dashboard: BareDashboardLink
}

interface BareDashboardLink {
    id: number
    name: string
}

// insight activity logs changed the format that dashboard changes were reported in
type DashboardLink = TileStyleDashboardLink | BareDashboardLink

const unboxBareLink = (boxedLink: DashboardLink): BareDashboardLink => {
    if ('dashboard' in boxedLink) {
        return boxedLink.dashboard
    }
    return boxedLink
}

const linkToDashboard = (dashboard: BareDashboardLink): JSX.Element => (
    <div className="highlighted-activity">
        <Link to={urls.dashboard(dashboard.id)}>{dashboard.name}</Link>
    </div>
)

function describeInsightRename(
    change?: ActivityChange,
    logItem?: ActivityLogItem,
    asNotification?: boolean
): ChangeMapping {
    return {
        description: [
            <>
                renamed {asNotification && 'the insight '}"{change?.before}" to{' '}
                <strong>"{nameOrLinkToInsight(logItem?.detail.short_id, change?.after as string)}"</strong>
            </>,
        ],
        summary: [
            <>
                renamed "{change?.before}" to "{change?.after}"
            </>,
        ],
        suffix: <></>,
    }
}

// `filters` is no longer a field on the insight model, but old log entries still record changes to
// it, so the activity log reads a wider set of fields than the model now carries.
type LoggedInsightField = keyof InsightModel | 'filters'

const insightActionsMapping: Record<
    LoggedInsightField,
    (change?: ActivityChange, logItem?: ActivityLogItem, asNotification?: boolean) => ChangeMapping | null
> = {
    name: describeInsightRename,
    filters: function onChangedFilter(change) {
        const filtersAfter = change?.after as Partial<FilterType>

        // Only an insight written before queries logs this field, so these entries are years old and
        // no new one can be written. Summarizing the definition would mean converting legacy filters,
        // which no other read path still does, and the headline reads the same either way.
        return areObjectValuesEmpty(filtersAfter) ? null : { description: ['changed query definition'] }
    },
    query: function onChangedQuery(change) {
        if (change?.action === 'deleted') {
            // if the query was deleted, then someone has added a filter and that will be summarized
            return null
        }

        const queryAfter = change?.after as QuerySchema
        // saved insights store the actual query wrapped in an InsightVizNode (or in a
        // DataVisualizationNode / DataTableNode for SQL insights), so summarize the source
        const source =
            isInsightVizNode(queryAfter) ||
            isDataVisualizationNode(queryAfter) ||
            isDataTableNodeWithHogQLQuery(queryAfter)
                ? queryAfter.source
                : queryAfter
        return isInsightQueryNode(source) || isHogQLQuery(source)
            ? summarizeQueryChanges(source)
            : { description: ['changed the query'] }
    },
    deleted: function onSoftDelete(change, logItem, asNotification) {
        const isDeleted = detectBoolean(change?.after)
        const describeChange = isDeleted ? 'deleted' : 'restored'
        return {
            summary: [`${describeChange} the insight`],
            description: [
                <>
                    {describeChange}
                    {asNotification && ' the insight '}
                </>,
            ],
            suffix: <>{nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}</>,
        }
    },
    short_id: function onShortId(change, _, asNotification) {
        return {
            summary: [
                <>
                    changed the short id to <strong>"{change?.after as string}"</strong>
                </>,
            ],
            description: [
                <>
                    changed the short id {asNotification && ' of the insight '}to{' '}
                    <strong>"{change?.after as string}"</strong>
                </>,
            ],
        }
    },
    derived_name: describeInsightRename,
    description: function onDescription(change, _, asNotification) {
        return describeDescriptionChange(change, asNotification, 'insight')
    },
    favorited: function onFavorited(change, logItem, asNotification) {
        const isFavoriteAfter = detectBoolean(change?.after)
        return {
            summary: [isFavoriteAfter ? 'favorited the insight' : 'unfavorited the insight'],
            description: [
                <>
                    <div className="highlighted-activity">
                        {isFavoriteAfter ? '' : 'un-'}favorited{asNotification && ' the insight '}
                    </div>
                </>,
            ],
            suffix: <>{nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}</>,
        }
    },
    tags: describeTagChanges,
    dashboards: function onDashboardsChange(change, logItem, asNotification) {
        const dashboardsBefore = (change?.before as DashboardLink[]).map(unboxBareLink)
        const dashboardsAfter = (change?.after as DashboardLink[]).map(unboxBareLink)

        const addedDashboards = dashboardsAfter.filter(
            (after) => !dashboardsBefore.some((before) => before.id === after.id)
        )
        const removedDashboards = dashboardsBefore.filter(
            (before) => !dashboardsAfter.some((after) => after.id === before.id)
        )

        const addedSentence = addedDashboards.length ? (
            <SentenceList
                prefix={
                    <>
                        added {asNotification && ' the insight '}
                        {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)} to
                    </>
                }
                listParts={addedDashboards.map((d) => (
                    <Fragment key={d.id}>{linkToDashboard(d)}</Fragment>
                ))}
            />
        ) : null

        const removedSentence = removedDashboards.length ? (
            <SentenceList
                prefix={
                    <>
                        removed {asNotification && ' the insight '}
                        {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)} from
                    </>
                }
                listParts={removedDashboards.map((d) => (
                    <Fragment key={d.id}>{linkToDashboard(d)}</Fragment>
                ))}
            />
        ) : null

        return {
            description: [addedSentence, removedSentence],
            summary: [
                addedDashboards.length ? (
                    <SentenceList
                        prefix="added to"
                        listParts={addedDashboards.map((dashboard) => (
                            <Fragment key={dashboard.id}>{linkToDashboard(dashboard)}</Fragment>
                        ))}
                    />
                ) : null,
                removedDashboards.length ? (
                    <SentenceList
                        prefix="removed from"
                        listParts={removedDashboards.map((dashboard) => (
                            <Fragment key={dashboard.id}>{linkToDashboard(dashboard)}</Fragment>
                        ))}
                    />
                ) : null,
            ],
            suffix: <></>,
        }
    },
    alerts: () => null,
    // fields that are excluded on the backend
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    updated_at: () => null,
    last_modified_at: () => null,
    order: () => null,
    result: () => null,
    last_refresh: () => null,
    cache_target_age: () => null,
    next_allowed_client_refresh: () => null,
    last_modified_by: () => null,
    next: () => null,
    saved: () => null,
    is_sample: () => null,
    timezone: () => null,
    disable_baseline: () => null,
    dashboard_tiles: () => null,
    query_status: () => null,
    query_scan: () => null,
    user_access_level: () => null,
    _create_in_folder: () => null,
    last_viewed_at: () => null,
    viewers: () => null,
    view_count: () => null,
    is_cached: () => null,
    filter_override_context: () => null,
    columns: () => null,
    types: () => null,
    resolved_date_range: () => null,
}

function summarizeQueryChanges(query: InsightQueryNode | HogQLQuery): ChangeMapping {
    return {
        description: ['changed query definition'],
        extendedDescription: (
            <div className="ActivityDescription">
                <SeriesSummary query={query} />
                <PropertiesSummary properties={isHogQLQuery(query) ? query.filters?.properties : query.properties} />
                <InsightBreakdownSummary query={query} />
            </div>
        ),
    }
}

function describeInsightUpdate(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange | null {
    const mappings: ChangeMapping[] = []
    try {
        for (const change of logItem.detail.changes || []) {
            const handler = insightActionsMapping[change.field as LoggedInsightField]
            if (!change?.field || !handler) {
                continue
            }
            const result = handler(change, logItem, asNotification)
            if (result) {
                mappings.push(result)
            }
        }
    } catch (e) {
        console.error('Error while summarizing insight update', e)
        posthog.captureException(e)
    }
    return describeChangeMappings(
        logItem,
        mappings,
        nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name),
        <>
            on {asNotification && ' the insight '}
            {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}
        </>
    )
}

function describeInsightAuthentication(logItem: ActivityLogItem): HumanizedChange {
    const afterData = logItem.detail.changes?.[0]?.after as any
    const clientIp = afterData?.client_ip || 'unknown IP'
    const passwordNote = afterData?.password_note || 'unknown password'

    return {
        summary: activityLogSummary(
            logItem,
            'Authenticated to the shared insight',
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name),
            `From ${clientIp} using password ${passwordNote}`,
            <strong>Anonymous user</strong>
        ),
        description: (
            <>
                <strong>Anonymous user</strong> successfully authenticated to shared insight{' '}
                {nameOrLinkToInsight(logItem?.detail.short_id, logItem.detail.name)} from {clientIp} using password{' '}
                <strong>{passwordNote}</strong>
            </>
        ),
    }
}

function describeInsightAuthenticationFailure(logItem: ActivityLogItem): HumanizedChange {
    const afterData = logItem.detail.changes?.[0]?.after as any
    const clientIp = afterData?.client_ip || 'unknown IP'

    return {
        summary: activityLogSummary(
            logItem,
            'Failed to authenticate to the shared insight',
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name),
            `From ${clientIp}`,
            <strong>Anonymous user</strong>
        ),
        description: (
            <>
                <strong>Anonymous user</strong> failed to authenticate to shared insight{' '}
                {nameOrLinkToInsight(logItem?.detail.short_id, logItem.detail.name)} from {clientIp}
            </>
        ),
    }
}

function describeInsightExport(logItem: ActivityLogItem): HumanizedChange {
    const exportFormat = logItem.detail.changes?.[0]?.after
    let exportType = 'in an unknown format'
    if (typeof exportFormat === 'string') {
        exportType = exportFormat.split('/')[1]
    }

    return {
        summary: activityLogSummary(
            logItem,
            `Exported as ${exportType}`,
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name)
        ),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> exported{' '}
                {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)} as a {exportType}
            </>
        ),
    }
}

function describeInsightCreated(logItem: ActivityLogItem): HumanizedChange {
    return {
        summary: activityLogSummary(
            logItem,
            'Created the insight',
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name)
        ),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> created the insight:{' '}
                {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}
            </>
        ),
    }
}

function describeInsightDeleted(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    return {
        summary: activityLogSummary(logItem, 'Deleted the insight', logItem.detail.name || 'Insight'),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> deleted {asNotification ? 'your' : 'the'} insight:{' '}
                {logItem.detail.name}
            </>
        ),
    }
}

function describeInsightPreviewExport(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    return {
        summary: activityLogSummary(
            logItem,
            'Exported a preview image for the shared link',
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name),
            undefined,
            <strong>PostHog</strong>
        ),
        description: (
            <>
                <strong>PostHog</strong> exported {asNotification ? 'your' : 'the'} insight: {logItem.detail.name} as an
                image for the shared insight link.
            </>
        ),
    }
}

function describeInsightSharingEnabled(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    return {
        summary: activityLogSummary(
            logItem,
            'Enabled sharing',
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name)
        ),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> shared {asNotification ? 'your' : 'the'} insight:{' '}
                {logItem.detail.name}.
            </>
        ),
    }
}

function describeInsightSharingDisabled(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    return {
        summary: activityLogSummary(
            logItem,
            'Deleted the shared link',
            nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name)
        ),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> deleted shared link for {asNotification ? 'your' : 'the'}{' '}
                insight: {logItem.detail.name}.
            </>
        ),
    }
}

const INSIGHT_ACTIVITY_DESCRIBERS = new Map<
    string,
    (logItem: ActivityLogItem, asNotification?: boolean) => HumanizedChange | null
>([
    ['created', describeInsightCreated],
    ['deleted', describeInsightDeleted],
    ['exported for opengraph image', describeInsightPreviewExport],
    ['sharing enabled', describeInsightSharingEnabled],
    ['sharing disabled', describeInsightSharingDisabled],
    ['updated', describeInsightUpdate],
    ['exported', describeInsightExport],
    ['share_login_success', describeInsightAuthentication],
    ['share_login_failed', describeInsightAuthenticationFailure],
])

export function insightActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Insight') {
        console.error('insight describer received a non-insight activity')
        return { description: null }
    }

    const describer = INSIGHT_ACTIVITY_DESCRIBERS.get(logItem.activity)
    const description = describer?.(logItem, asNotification)
    if (description) {
        return description
    }

    return defaultDescriber(
        logItem,
        asNotification,
        nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)
    )
}
