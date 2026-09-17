import posthog from 'posthog-js'
import { Fragment } from 'react'

import {
    describeDescriptionChange,
    describeTagChanges,
} from 'lib/components/ActivityLog/activityDescriptions/changeDescriptions'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    Description,
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

const insightActionsMapping: Record<
    keyof InsightModel,
    (change?: ActivityChange, logItem?: ActivityLogItem, asNotification?: boolean) => ChangeMapping | null
> = {
    name: function onName(change, logItem, asNotification) {
        return {
            description: [
                <>
                    renamed {asNotification && 'the insight '}"{change?.before}" to{' '}
                    <strong>"{nameOrLinkToInsight(logItem?.detail.short_id, change?.after as string)}"</strong>
                </>,
            ],
            suffix: <></>,
        }
    },
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
            description: [
                <>
                    changed the short id {asNotification && ' of the insight '}to{' '}
                    <strong>"{change?.after as string}"</strong>
                </>,
            ],
        }
    },
    derived_name: function onDerivedName(change, logItem, asNotification) {
        return {
            description: [
                <>
                    renamed {asNotification && ' the insight '}"{change?.before}" to{' '}
                    <strong>"{nameOrLinkToInsight(logItem?.detail.short_id, change?.after as string)}"</strong>
                </>,
            ],
            suffix: <></>,
        }
    },
    description: function onDescription(change, _, asNotification) {
        return {
            description: describeDescriptionChange(change, asNotification, 'insight'),
            summary: [change?.after ? 'Changed the description' : 'Cleared the description'],
            preview: typeof change?.after === 'string' ? change.after : undefined,
        }
    },
    favorited: function onFavorited(change, logItem, asNotification) {
        const isFavoriteAfter = detectBoolean(change?.after)
        return {
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
                        prefix="Added to"
                        listParts={addedDashboards.map((dashboard) => (
                            <Fragment key={dashboard.id}>{linkToDashboard(dashboard)}</Fragment>
                        ))}
                    />
                ) : null,
                removedDashboards.length ? (
                    <SentenceList
                        prefix="Removed from"
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

export function insightActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Insight') {
        console.error('insight describer received a non-insight activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
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

    if (logItem.activity == 'deleted') {
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

    if (logItem.activity == 'exported for opengraph image') {
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
                    <strong>PostHog</strong> exported {asNotification ? 'your' : 'the'} insight: {logItem.detail.name}{' '}
                    as an image for the shared insight link.
                </>
            ),
        }
    }

    if (logItem.activity == 'sharing enabled') {
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

    if (logItem.activity == 'sharing disabled') {
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

    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let summaryChanges: Description[] = []
        let preview: string | undefined
        let extendedDescription: JSX.Element | undefined
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the insight '}
                {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}
            </>
        )

        try {
            for (const change of logItem.detail.changes || []) {
                const insightAction = insightActionsMapping[change.field as keyof InsightModel]
                if (!change?.field || !insightAction) {
                    continue // insight updates have to have a "field" to be described
                }

                const actionHandler = insightAction
                const processedChange = actionHandler(change, logItem, asNotification)
                if (processedChange === null) {
                    continue // unexpected log from backend is indescribable
                }

                const {
                    description,
                    extendedDescription: _extendedDescription,
                    suffix,
                    summary,
                    preview: changePreview,
                } = processedChange
                summaryChanges = summaryChanges.concat(summary ?? description ?? [])
                preview = changePreview ?? preview
                if (description) {
                    changes = changes.concat(description)
                }
                if (_extendedDescription) {
                    extendedDescription = _extendedDescription
                }
                if (suffix) {
                    changeSuffix = suffix
                }
            }
        } catch (e) {
            console.error('Error while summarizing insight update', e)
            posthog.captureException(e)
        }

        if (changes.length) {
            return {
                summary: activityLogSummary(
                    logItem,
                    <SentenceList listParts={summaryChanges} />,
                    nameOrLinkToInsight(logItem.detail.short_id, logItem.detail.name),
                    preview
                ),
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        suffix={changeSuffix}
                    />
                ),
                extendedDescription,
            }
        }
    }
    if (logItem.activity === 'exported') {
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

    if (logItem.activity === 'share_login_success') {
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

    if (logItem.activity === 'share_login_failed') {
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

    return defaultDescriber(
        logItem,
        asNotification,
        nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)
    )
}
