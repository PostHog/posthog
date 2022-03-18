import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { FeatureFlagFilters, FeatureFlagType } from '~/types'
import React from 'react'
import { groupFilters } from 'scenes/feature-flags/FeatureFlags'

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
                changed the description to "{change?.after}" on {nameOrLinkToFlag(item)}
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
        // "string value (multivariate test)" looks like {"variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test_sticky", "rollout_percentage": 50}]}
        // "boolean value" with condition looks like {"groups":[{"properties":[{"key":"$initial_browser_version","type":"person","value":["100"],"operator":"exact"}],"rollout_percentage":35}],"multivariate":null}
        // "boolean value" with no condition looks like {"groups":[{"properties":[],"rollout_percentage":99}],"multivariate":null}

        const filters = change?.after as FeatureFlagFilters

        const isBooleanValueFlag = Array.isArray(filters.groups) && filters.groups.length >= 1

        if (isBooleanValueFlag) {
            //simple flag with no condition
            return (
                <>
                    changed the rollout percentage to {groupFilters(filters.groups)} on {nameOrLinkToFlag(item)}
                </>
            )
        }
        // TODO is it true that it must be multivariate now
        return (
            <>
                changed the rollout percentage for the variants to{' '}
                {filters.multivariate?.variants.map((v) => `${v.key}: ${v.rollout_percentage}`).join(', ')} on{' '}
                {nameOrLinkToFlag(item)}
            </>
        )
    },
    deleted: function onSoftDelete(item) {
        return <>deleted the flag: {item.detail.name}</>
    },
    rollout_percentage: function onRolloutPercentage(item, change) {
        return (
            <>
                changed rollout percentage to {change?.after}% on {nameOrLinkToFlag(item)}
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
        ;(logItem.detail.changes || []).forEach((change) => {
            if (!change?.field) {
                return
            }

            descriptions.push(featureFlagActionsMapping[change?.field](logItem, change))
        })
    }
    return descriptions
}
