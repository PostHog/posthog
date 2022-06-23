import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { Description, FilterType, InsightModel } from '~/types'
import React from 'react'
import { SentenceList } from 'scenes/feature-flags/activityDescriptions'
import { BreakdownSummary, FiltersSummary, QuerySummary } from 'lib/components/InsightCard/InsightDetails'
import '../../lib/components/InsightCard/InsightCard.scss'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { pluralize } from 'lib/utils'
import { INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED } from 'lib/components/InsightCard/InsightCard'

const nameOrLinkToInsight = (item: ActivityLogItem): string | JSX.Element => {
    const name = item.detail.name || '(empty string)'
    return item.detail.short_id ? <Link to={urls.insightView(item.detail.short_id)}>{name}</Link> : name
}

interface DashboardLink {
    id: number
    name: string
}

const linkToDashboard = (dashboard: DashboardLink): JSX.Element => (
    <div className="highlighted-activity">
        dashboard <Link to={urls.dashboard(dashboard.id)}>{dashboard.name}</Link>
    </div>
)

const insightActionsMapping: Record<keyof InsightModel, (change?: ActivityChange) => Description[] | null> = {
    name: function onName(change) {
        return [
            <>
                changed the name to <strong>"{change?.after}"</strong>
            </>,
        ]
    },
    filters: function onChangedFilter(change) {
        // const filtersBefore = change?.before as FeatureFlagFilters
        const filtersAfter = change?.after as Partial<FilterType>

        const changes: Description[] = []

        if (filtersAfter.insight && INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED.includes(filtersAfter.insight)) {
            changes.push(<>changed details</>)
        } else {
            changes.push(
                <>
                    changed details to:
                    <div className="summary-card">
                        <QuerySummary filters={filtersAfter} />
                        <FiltersSummary filters={filtersAfter} />
                        {filtersAfter.breakdown_type && <BreakdownSummary filters={filtersAfter} />}
                    </div>
                </>
            )
        }

        if (changes.length > 0) {
            return changes
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete() {
        return [<>deleted the insight</>]
    },
    short_id: function onShortId(change) {
        return [
            <>
                changed the short id to <strong>"{change?.after}"</strong>
            </>,
        ]
    },
    derived_name: function onDerivedName(change) {
        return [
            <>
                changed the name to <strong>"{change?.after}"</strong>
            </>,
        ]
    },
    description: function onDescription(change) {
        return [
            <>
                changed the description to <strong>"{change?.after}"</strong>
            </>,
        ]
    },
    favorited: function onFavorited(change) {
        const isFavoriteAfter = change?.after as boolean
        return [
            <>
                <div className="highlighted-activity">{isFavoriteAfter ? '' : 'un-'}favorited the insight</div>
            </>,
        ]
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
                    added the {pluralize(addedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={addedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedTags.length) {
            changes.push(
                <>
                    removed the {pluralize(removedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={removedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        return changes
    },
    dashboards: function onDashboardsChange(change) {
        const dashboardsBefore = change?.before as DashboardLink[]
        const dashboardsAfter = change?.after as DashboardLink[]

        const addedDashboards = dashboardsAfter.filter(
            (after) => !dashboardsBefore.some((before) => before.id === after.id)
        )
        const removedDashboards = dashboardsBefore.filter(
            (before) => !dashboardsAfter.some((after) => after.id === before.id)
        )

        const describeAdded = addedDashboards.map((d) => <>added to {linkToDashboard(d)}</>)
        const describeRemoved = removedDashboards.map((d) => <>removed from {linkToDashboard(d)}</>)

        return describeAdded.concat(describeRemoved)
    },
    // fields that are excluded on the backend
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    filters_hash: () => null,
    layouts: () => null,
    color: () => null,
    refreshing: () => null,
    updated_at: () => null,
    last_modified_at: () => null,
    order: () => null,
    result: () => null,
    last_refresh: () => null,
    last_modified_by: () => null,
    next: () => null, // only used by frontend
    saved: () => null,
    is_sample: () => null,
    timezone: () => null,
    effective_restriction_level: () => null, // read from dashboards
    effective_privilege_level: () => null, // read from dashboards
}

export function insightActivityDescriber(logItem: ActivityLogItem, users_name: string): string | JSX.Element | null {
    if (logItem.scope != 'Insight') {
        console.error('insight describer received a non-insight activity')
        return null
    }

    if (logItem.activity == 'created') {
        return (
            <>
                <strong>{users_name}</strong> created the insight: {nameOrLinkToInsight(logItem)}
            </>
        )
    }
    if (logItem.activity == 'deleted') {
        return (
            <>
                <strong>{users_name}</strong> deleted the insight: {logItem.detail.name}
            </>
        )
    }
    if (logItem.activity == 'updated') {
        let changes: Description[] = []

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // insight updates have to have a "field" to be described
            }

            const nextChange: Description[] | null = insightActionsMapping[change.field](change)
            if (nextChange) {
                changes = changes.concat(nextChange)
            }
        }

        if (changes.length) {
            return (
                <SentenceList
                    listParts={changes}
                    prefix={
                        <>
                            On {nameOrLinkToInsight(logItem)}, <strong>{users_name}</strong>
                        </>
                    }
                />
            )
        }
    }

    return null
}
