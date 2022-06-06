import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ChangeDescriptions, FilterType, InsightModel } from '~/types'
import React from 'react'
import { SentenceList } from 'scenes/feature-flags/activityDescriptions'
import { BreakdownSummary, FiltersSummary, QuerySummary } from 'lib/components/InsightCard/InsightDetails'
import '../../lib/components/InsightCard/InsightCard.scss'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { pluralize } from 'lib/utils'

const nameOrLinkToInsight = (item: ActivityLogItem): string | JSX.Element => {
    const name = item.detail.name || '(empty string)'
    return item.detail.short_id ? <Link to={urls.insightView(item.detail.short_id)}>{name}</Link> : name
}

function linkToDashboard(dashboardId: number): JSX.Element {
    // todo need a name for the dashboard?
    return <Link to={urls.dashboard(dashboardId)}>dashboard</Link>
}

const insightActionsMapping: Record<keyof InsightModel, (change?: ActivityChange) => ChangeDescriptions | null> = {
    name: function onName(change) {
        return {
            descriptions: [
                <>
                    changed the name to <strong>"{change?.after}"</strong>
                </>,
            ],
            bareName: false,
        }
    },
    filters: function onChangedFilter(change) {
        // const filtersBefore = change?.before as FeatureFlagFilters
        const filtersAfter = change?.after as Partial<FilterType>

        const changes: (string | JSX.Element | null)[] = []

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
        if (changes.length > 0) {
            return { descriptions: changes, bareName: false }
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete() {
        return { descriptions: [<>deleted</>], bareName: true }
    },
    short_id: function onShortId(change) {
        return {
            descriptions: [
                <>
                    changed the short id to <strong>"{change?.after}"</strong>
                </>,
            ],
            bareName: false,
        }
    },
    derived_name: function onDerivedName(change) {
        return {
            descriptions: [
                <>
                    changed the name to <strong>"{change?.after}"</strong>
                </>,
            ],
            bareName: false,
        }
    },
    description: function onDescription(change) {
        return {
            descriptions: [
                <>
                    changed the description to <strong>"{change?.after}"</strong>
                </>,
            ],
            bareName: false,
        }
    },
    favorited: function onFavorited(change) {
        const isFavoriteAfter = change?.after as boolean
        return {
            descriptions: [
                <>
                    <div className="highlighted-activity">{isFavoriteAfter ? '' : 'un-'}favorited</div>
                </>,
            ],
            bareName: true,
        }
    },
    tags: function onTags(change) {
        const tagsBefore = change?.before as string[]
        const tagsAfter = change?.after as string[]
        const addedTags = tagsAfter.filter((t) => tagsBefore.indexOf(t) === -1)
        const removedTags = tagsBefore.filter((t) => tagsAfter.indexOf(t) === -1)

        const changes: (string | JSX.Element | null)[] = []
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
        return { descriptions: changes, bareName: false }
    },
    effective_restriction_level: function onRestrictionChange(change) {
        return {
            descriptions: [
                <>
                    set restriction <pre>{JSON.stringify(change)}</pre>
                </>,
            ],
            bareName: false,
        }
    },
    effective_privilege_level: function onPrivilegeChange(change) {
        return {
            descriptions: [
                <>
                    set privilege <pre>{JSON.stringify(change)}</pre>
                </>,
            ],
            bareName: false,
        }
    },
    dashboards: function onDashboardsChange(change) {
        const dashboardsBefore = (change?.before as string[]).map((dashboard) => {
            return Number.parseInt(dashboard.replace('Dashboard object (', '').replace(')', ''))
        })
        const dashboardsAfter = (change?.after as string[]).map((dashboard) => {
            return Number.parseInt(dashboard.replace('Dashboard object (', '').replace(')', ''))
        })

        const addedDashboards = dashboardsAfter.filter((da) => !dashboardsBefore.includes(da))
        const removedDashboards = dashboardsBefore.filter((db) => !dashboardsAfter.includes(db))

        const describeAdded = addedDashboards.map((d) => <>added to {linkToDashboard(d)}</>)
        const describeRemoved = removedDashboards.map((d) => <>removed from {linkToDashboard(d)}</>)

        return { descriptions: describeAdded.concat(describeRemoved), bareName: true }
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
}

export function insightActivityDescriber(logItem: ActivityLogItem): string | JSX.Element | null {
    if (logItem.scope != 'Insight') {
        console.error('insight describer received a non-insight activity')
        return null
    }

    if (logItem.activity == 'created') {
        return <>created the insight: {nameOrLinkToInsight(logItem)}</>
    }
    if (logItem.activity == 'deleted') {
        return <>deleted the insight: {logItem.detail.name}</>
    }
    if (logItem.activity == 'updated') {
        const changes: ChangeDescriptions = { descriptions: [], bareName: false }

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // insight updates have to have a "field" to be described
            }

            const nextChange: ChangeDescriptions | null = insightActionsMapping[change.field](change)
            if (nextChange?.descriptions) {
                changes.descriptions = changes.descriptions.concat(nextChange?.descriptions)
                changes.bareName = nextChange?.bareName
            }
        }

        if (changes.descriptions.length) {
            const sayOn = changes.bareName ? '' : 'on'
            return (
                <SentenceList
                    listParts={changes.descriptions}
                    suffix={
                        <>
                            {sayOn} {nameOrLinkToInsight(logItem)}
                        </>
                    }
                />
            )
        }
    }

    return null
}
