import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ChangeDescriptions, FilterType, InsightModel } from '~/types'
import React from 'react'
import { BreakdownSummary, FiltersSummary, QuerySummary } from 'lib/components/InsightCard/InsightDetails'
import '../../lib/components/InsightCard/InsightCard.scss'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { pluralize } from 'lib/utils'
import { INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED } from 'lib/components/InsightCard/InsightCard'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

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
    effective_restriction_level: () => null, // read from dashboards
    effective_privilege_level: () => null, // read from dashboards
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
    if (logItem.activity === 'exported') {
        const exportFormat = logItem.detail.changes?.[0]?.after
        let exportType = 'in an unknown format'
        if (typeof exportFormat === 'string') {
            exportType = exportFormat.split('/')[1]
        }

        return (
            <>
                exported the insight {nameOrLinkToInsight(logItem)} as a {exportType}
            </>
        )
    }

    return null
}
