import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { FeatureFlagFilters, FeatureFlagType } from '~/types'
import React from 'react'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

const nameOrLinkToFlag = (item: ActivityLogItem): string | JSX.Element => {
    const name = item.detail.name || '(empty string)'
    return item.item_id ? <Link to={urls.featureFlag(item.item_id)}>{name}</Link> : name
}

type flagFields = keyof FeatureFlagType

const featureFlagActionsMapping: {
    [field in flagFields]: (item: ActivityLogItem, change?: ActivityChange) => string | JSX.Element | null
} = {
    name: function onName(item, change) {
        return (
            <>
                changed the description to <strong>"{change?.after}"</strong> on {nameOrLinkToFlag(item)}
            </>
        )
    },
    active: function onActive(item, change) {
        const describeChange = change?.after ? 'enabled' : 'disabled'
        return (
            <>
                {describeChange} the flag: {nameOrLinkToFlag(item)}
            </>
        )
    },
    filters: function onChangedFilter(item, change) {
        const filtersBefore = change?.before as FeatureFlagFilters
        const filtersAfter = change?.after as FeatureFlagFilters

        const isBooleanValueFlag = Array.isArray(filtersAfter.groups)

        if (isBooleanValueFlag) {
            if (
                filtersAfter.groups.length === 0 ||
                !filtersAfter.groups.some((group) => group.rollout_percentage !== 0)
            ) {
                // there are no rollout groups or all are at 0%
                return <>set the flag {nameOrLinkToFlag(item)} to apply to no users</>
            }

            const changedFilters: JSX.Element[] = []
            filtersAfter.groups
                .filter((groupAfter, index) => {
                    const groupBefore = filtersBefore?.groups?.[index]
                    // only keep changes with no before state, or those where before and after are different
                    return !groupBefore || JSON.stringify(groupBefore) !== JSON.stringify(groupAfter)
                })
                .forEach((groupAfter) => {
                    const { properties, rollout_percentage = null } = groupAfter
                    if (properties?.length > 0) {
                        changedFilters.push(
                            <>
                                <div>
                                    <strong>{rollout_percentage ?? 100}%</strong> of
                                </div>
                                <PropertyFiltersDisplay filters={properties} />
                            </>
                        )
                    } else {
                        changedFilters.push(
                            <>
                                <strong>{rollout_percentage ?? 100}%</strong> of <strong>all users</strong>
                            </>
                        )
                    }
                })
            if (changedFilters.length) {
                // always starts with a single label, must have 2 or more to include descriptions
                return (
                    <div className="change-list">
                        <div>set the flag {nameOrLinkToFlag(item)} to apply to&nbsp;</div>
                        {changedFilters.flatMap((changedFilter, index, all) => {
                            const isntFirst = index > 0
                            const isLast = index === all.length - 1
                            return (
                                <div key={index}>
                                    {isntFirst && <div>,&nbsp;</div>}
                                    {isLast && all.length >= 2 && <div>and&nbsp;</div>}
                                    {changedFilter}
                                </div>
                            )
                        })}
                    </div>
                )
            }
        }

        if (filtersAfter.multivariate) {
            return (
                <div className="change-list">
                    changed the rollout percentage for the variants to{' '}
                    {filtersAfter.multivariate?.variants.map((v, index, all) => {
                        const isntFirst = index > 0
                        const isLast = index === all.length - 1
                        return (
                            <div key={v.key}>
                                {isntFirst && <div>,&nbsp;</div>}
                                {isLast && all.length >= 2 && <div>and&nbsp;</div>}
                                <div className="highlighted-activity">
                                    {v.key}: <strong>{v.rollout_percentage}%</strong>
                                </div>
                            </div>
                        )
                    })}
                    &nbsp;on {nameOrLinkToFlag(item)}
                </div>
            )
        }

        console.error({ item, change }, 'could not describe log item')
        return null
    },
    deleted: function onSoftDelete(item) {
        return <>deleted the flag: {item.detail.name}</>
    },
    rollout_percentage: function onRolloutPercentage(item, change) {
        return (
            <>
                changed rollout percentage to <div className="highlighted-activity">{change?.after}%</div> on{' '}
                {nameOrLinkToFlag(item)}
            </>
        )
    },
    key: function onKey(item, change) {
        return (
            <>
                changed flag key from ${change?.before} to {nameOrLinkToFlag(item)}
            </>
        )
    },
    // fields that shouldn't show in the log if they change
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    is_simple_flag: () => null,
}

export function flagActivityDescriber(logItem: ActivityLogItem): (string | JSX.Element | null)[] {
    if (logItem.scope != 'FeatureFlag') {
        return [] // currently, only humanizes the feature flag scope
    }
    const descriptions = []
    if (logItem.activity == 'created') {
        descriptions.push(<>created the flag: {nameOrLinkToFlag(logItem)}</>)
    }
    if (logItem.activity == 'deleted') {
        descriptions.push(<>deleted the flag: {logItem.detail.name}</>)
    }
    if (logItem.activity == 'updated') {
        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // model changes have to have a "field" to be described
            }

            descriptions.push(featureFlagActionsMapping[change.field](logItem, change))
        }
    }
    return descriptions
}
