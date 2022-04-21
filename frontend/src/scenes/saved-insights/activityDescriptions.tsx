import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { InsightModel } from '~/types'
import React from 'react'
import { SentenceList } from 'scenes/feature-flags/activityDescriptions'

const nameOrLinkToInsight = (item: ActivityLogItem): string | JSX.Element => {
    const name = item.detail.name || '(empty string)'
    return item.detail.short_id ? <Link to={urls.insightView(item.detail.short_id)}>{name}</Link> : name
}

type Description = string | JSX.Element | null

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
        // const filtersAfter = change?.after as FeatureFlagFilters

        const changes: (string | JSX.Element | null)[] = []

        changes.push(<>changed settings</>)
        if (changes.length > 0) {
            return changes
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete() {
        return [<>deleted</>]
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
    favorited: function onFavorited() {
        return [
            <>
                <div className="highlighted-activity">favorited</div>
            </>,
        ]
    },
    saved: function onSaved() {
        return [
            <>
                <div className="highlighted-activity">saved</div>
            </>,
        ]
    },
    is_sample: function onIsSample() {
        return [
            <>
                set as <div className="highlighted-activity">a sample graph for dashboard templates</div>
            </>,
        ]
    },
    tags: function onTags(change) {
        // TODO how are tags presented as a change?
        return [
            <>
                added the tags <pre>{JSON.stringify(change)}</pre>
            </>,
        ]
    },
    effective_restriction_level: function onRestrictionChange(change) {
        return [
            <>
                set restriction <pre>{JSON.stringify(change)}</pre>
            </>,
        ]
    },
    effective_privilege_level: function onPrivilegeChange(change) {
        return [
            <>
                set privilege <pre>{JSON.stringify(change)}</pre>
            </>,
        ]
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
    dashboard: () => null,
    last_modified_by: () => null,
    next: () => null, // only used by frontend
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
        let changes: (string | JSX.Element | null)[] = []

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // insight updates have to have a "field" to be described
            }

            changes = changes.concat(insightActionsMapping[change.field](change))
        }

        if (changes.length) {
            return <SentenceList listParts={changes} suffix={<> the insight: {nameOrLinkToInsight(logItem)}</>} />
        }
    }

    return null
}
