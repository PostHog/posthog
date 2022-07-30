import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { FilterType, InsightModel, InsightShortId } from '~/types'
import React from 'react'
import { BreakdownSummary, FiltersSummary, QuerySummary } from 'lib/components/InsightCard/InsightDetails'
import '../../lib/components/InsightCard/InsightCard.scss'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { pluralize } from 'lib/utils'
import { INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED } from 'lib/components/InsightCard/InsightCard'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

const nameOrLinkToInsight = (short_id?: InsightShortId | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return short_id ? <Link to={urls.insightView(short_id)}>{displayName}</Link> : displayName
}

interface DashboardLink {
    id: number
    name: string
}

const linkToDashboard = (dashboard: DashboardLink): JSX.Element => (
    <div className="highlighted-activity">
        <Link to={urls.dashboard(dashboard.id)}>{dashboard.name}</Link>
    </div>
)

const insightActionsMapping: Record<
    keyof InsightModel,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    name: function onName(change, logItem) {
        return {
            description: [
                <>
                    renamed "{change?.before}" to{' '}
                    <strong>"{nameOrLinkToInsight(logItem?.detail.short_id, change?.after as string)}"</strong>
                </>,
            ],
            suffix: <></>,
        }
    },
    filters: function onChangedFilter(change) {
        // const filtersBefore = change?.before as FeatureFlagFilters
        const filtersAfter = change?.after as Partial<FilterType>
        let extendedDescription: JSX.Element | undefined = undefined
        const changes: Description[] = []

        if (filtersAfter.insight && INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED.includes(filtersAfter.insight)) {
            changes.push(<>changed details</>)
        } else {
            changes.push(<>changed details</>)
            extendedDescription = (
                <div className="summary-card">
                    <QuerySummary filters={filtersAfter} />
                    <FiltersSummary filters={filtersAfter} />
                    {filtersAfter.breakdown_type && <BreakdownSummary filters={filtersAfter} />}
                </div>
            )
        }

        if (changes.length > 0) {
            return { description: changes, extendedDescription }
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete(_, logItem) {
        return {
            description: [<>deleted</>],
            suffix: <>{nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}</>,
        }
    },
    short_id: function onShortId(change) {
        return {
            description: [
                <>
                    changed the short id to <strong>"{change?.after}"</strong>
                </>,
            ],
        }
    },
    derived_name: function onDerivedName(change, logItem) {
        return {
            description: [
                <>
                    renamed "{change?.before}" to{' '}
                    <strong>"{nameOrLinkToInsight(logItem?.detail.short_id, change?.after as string)}"</strong>
                </>,
            ],
            suffix: <></>,
        }
    },
    description: function onDescription(change) {
        return {
            description: [
                <>
                    changed the description to <strong>"{change?.after}"</strong>
                </>,
            ],
        }
    },
    favorited: function onFavorited(change, logItem) {
        const isFavoriteAfter = change?.after as boolean
        return {
            description: [
                <>
                    <div className="highlighted-activity">{isFavoriteAfter ? '' : 'un-'}favorited</div>
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
    dashboards: function onDashboardsChange(change, logItem) {
        const dashboardsBefore = change?.before as DashboardLink[]
        const dashboardsAfter = change?.after as DashboardLink[]

        const addedDashboards = dashboardsAfter.filter(
            (after) => !dashboardsBefore.some((before) => before.id === after.id)
        )
        const removedDashboards = dashboardsBefore.filter(
            (before) => !dashboardsAfter.some((after) => after.id === before.id)
        )

        const describeAdded = addedDashboards.map((d) => (
            <>
                added {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)} to {linkToDashboard(d)}
            </>
        ))
        const describeRemoved = removedDashboards.map((d) => (
            <>
                removed {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)} from {linkToDashboard(d)}
            </>
        ))

        return { description: describeAdded.concat(describeRemoved), suffix: <></> }
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

export function insightActivityDescriber(logItem: ActivityLogItem): HumanizedChange {
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
                    <strong>{logItem.user.first_name}</strong> deleted the insight: {logItem.detail.name}
                </>
            ),
        }
    }
    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let extendedDescription: JSX.Element | undefined
        let changeSuffix: Description = <>on {nameOrLinkToInsight(logItem?.detail.short_id, logItem?.detail.name)}</>

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // insight updates have to have a "field" to be described
            }

            const {
                description,
                extendedDescription: _extendedDescription,
                suffix,
            } = insightActionsMapping[change.field](change, logItem)
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
