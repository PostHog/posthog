import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    detectBoolean,
    HumanizedChange,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { FilterType, InsightModel, InsightShortId } from '~/types'
import { BreakdownSummary, FiltersSummary, QuerySummary } from 'lib/components/Cards/InsightCard/InsightDetails'
import '../../lib/components/Cards/InsightCard/InsightCard.scss'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { areObjectValuesEmpty, pluralize } from 'lib/utils'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { InsightQueryNode, QuerySchema } from '~/queries/schema'
import { isInsightQueryNode } from '~/queries/utils'
import { captureException } from '@sentry/react'

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
    } else {
        return boxedLink
    }
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

        return areObjectValuesEmpty(filtersAfter) ? null : summarizeChanges(filtersAfter)
    },
    query: function onChangedQuery(change) {
        if (change?.action === 'deleted') {
            // if the query was deleted, then someone has added a filter and that will be summarized
            return null
        }

        const queryAfter = change?.after as QuerySchema
        return isInsightQueryNode(queryAfter)
            ? summarizeChanges(queryNodeToFilter(change?.after as InsightQueryNode))
            : { description: ["cannot yet summarize changes to this insight's query: " + queryAfter?.kind] }
    },
    deleted: function onSoftDelete(change, logItem, asNotification) {
        const isDeleted = detectBoolean(change?.after)
        const describeChange = isDeleted ? 'deleted' : 'un-deleted'
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
            description: [
                <>
                    changed the description {asNotification && ' of the insight '}to{' '}
                    <strong>"{change?.after as string}"</strong>
                </>,
            ],
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
    tags: function onTags(change) {
        const tagsBefore = change?.before as string[]
        const tagsAfter = change?.after as string[]
        const addedTags = tagsAfter.filter((t) => tagsBefore.indexOf(t) === -1)
        const removedTags = tagsBefore.filter((t) => tagsAfter.indexOf(t) === -1)

        const changes: Description[] = []
        if (addedTags.length) {
            changes.push(
                <>
                    added {pluralize(addedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={addedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedTags.length) {
            changes.push(
                <>
                    removed {pluralize(removedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={removedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }

        return { description: changes }
    },
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
                    <>{linkToDashboard(d)}</>
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
                    <>{linkToDashboard(d)}</>
                ))}
            />
        ) : null

        return { description: [addedSentence, removedSentence], suffix: <></> }
    },
    // fields that are excluded on the backend
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    updated_at: () => null,
    last_modified_at: () => null,
    order: () => null,
    result: () => null,
    last_refresh: () => null,
    next_allowed_client_refresh: () => null,
    last_modified_by: () => null,
    next: () => null, // only used by frontend
    saved: () => null,
    is_sample: () => null,
    timezone: () => null,
    effective_restriction_level: () => null, // read from dashboards
    effective_privilege_level: () => null, // read from dashboards
    disable_baseline: () => null,
    dashboard_tiles: () => null, // changes are sent as dashboards
}

function summarizeChanges(filtersAfter: Partial<FilterType>): ChangeMapping | null {
    return {
        description: ['changed query definition'],
        extendedDescription: (
            <div className="summary-card">
                <QuerySummary filters={filtersAfter} />
                <FiltersSummary filters={filtersAfter} />
                {filtersAfter.breakdown_type && <BreakdownSummary filters={filtersAfter} />}
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
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> created the insight:{' '}
                    {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> deleted {asNotification ? 'your' : 'the'} insight:{' '}
                    {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'exported for opengraph image') {
        return {
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
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> shared {asNotification ? 'your' : 'the'} insight:{' '}
                    {logItem.detail.name}.
                </>
            ),
        }
    }

    if (logItem.activity == 'sharing disabled') {
        return {
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> deleted shared link for {asNotification ? 'your' : 'the'}{' '}
                    insight: {logItem.detail.name}.
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let extendedDescription: JSX.Element | undefined
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the insight '}
                {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}
            </>
        )

        try {
            for (const change of logItem.detail.changes || []) {
                if (!change?.field || !insightActionsMapping[change.field]) {
                    continue // insight updates have to have a "field" to be described
                }

                const actionHandler = insightActionsMapping[change.field]
                const processedChange = actionHandler(change, logItem, asNotification)
                if (processedChange === null) {
                    continue // // unexpected log from backend is indescribable
                }

                const { description, extendedDescription: _extendedDescription, suffix } = processedChange
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
            captureException(e)
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<strong>{logItem.user.first_name}</strong>}
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
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> exported{' '}
                    {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)} as a {exportType}
                </>
            ),
        }
    }

    return { description: null }
}
