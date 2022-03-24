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

type FlagFields = keyof FeatureFlagType
type Description = string | JSX.Element | null

const featureFlagActionsMapping: {
    [field in FlagFields]: (change?: ActivityChange) => Description[] | null
} = {
    name: function onName(change) {
        return [
            <>
                changed the description to <strong>"{change?.after}"</strong>
            </>,
        ]
    },
    active: function onActive(change) {
        const describeChange = change?.after ? 'enabled' : 'disabled'
        return [<>{describeChange}</>]
    },
    filters: function onChangedFilter(change) {
        const filtersBefore = change?.before as FeatureFlagFilters
        const filtersAfter = change?.after as FeatureFlagFilters

        const isBooleanValueFlag = Array.isArray(filtersAfter?.groups)
        const isMultivariateFlag = filtersAfter?.multivariate

        const changes: (string | JSX.Element | null)[] = []

        if (isBooleanValueFlag) {
            if (
                filtersAfter.groups.length === 0 ||
                !filtersAfter.groups.some((group) => group.rollout_percentage !== 0)
            ) {
                // there are no rollout groups or all are at 0%
                changes.push(<>changed the filter conditions to apply to no users</>)
            } else {
                const groupChanges: (string | JSX.Element | null)[] = []

                filtersAfter.groups
                    .filter((groupAfter, index) => {
                        const groupBefore = filtersBefore?.groups?.[index]
                        // only keep changes with no before state, or those where before and after are different
                        return !groupBefore || JSON.stringify(groupBefore) !== JSON.stringify(groupAfter)
                    })
                    .forEach((groupAfter) => {
                        const { properties, rollout_percentage = null } = groupAfter
                        if (properties?.length > 0) {
                            groupChanges.push(
                                <>
                                    <div>
                                        <strong>{rollout_percentage ?? 100}%</strong> of
                                    </div>
                                    <PropertyFiltersDisplay filters={properties} />
                                </>
                            )
                        } else {
                            groupChanges.push(
                                <>
                                    <strong>{rollout_percentage ?? 100}%</strong> of <strong>all users</strong>
                                </>
                            )
                        }
                    })
                if (groupChanges.length) {
                    changes.push(
                        <SentenceList listParts={groupChanges} prefix="changed the filter conditions to apply to" />
                    )
                }
            }
        }

        if (isMultivariateFlag) {
            changes.push(
                <SentenceList
                    listParts={(filtersAfter.multivariate?.variants || []).map((v) => (
                        <div key={v.key} className="highlighted-activity">
                            {v.key}: <strong>{v.rollout_percentage}%</strong>
                        </div>
                    ))}
                    prefix="changed the rollout percentage for the variants to"
                />
            )
        }

        if (changes.length > 0) {
            return changes
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete() {
        return [<>deleted</>]
    },
    rollout_percentage: function onRolloutPercentage(change) {
        return [
            <>
                changed rollout percentage to <div className="highlighted-activity">{change?.after}%</div>
            </>,
        ]
    },
    key: function onKey(change) {
        return [<>changed flag key from ${change?.before}</>]
    },
    // fields that shouldn't show in the log if they change
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    is_simple_flag: () => null,
}

export function flagActivityDescriber(logItem: ActivityLogItem): string | JSX.Element | null {
    if (logItem.scope != 'FeatureFlag') {
        console.error('feature flag decsriber received a non-feature flag activity')
        return null // only humanizes the feature flag scope
    }

    if (logItem.activity == 'created') {
        return <>created the flag: {nameOrLinkToFlag(logItem)}</>
    }
    if (logItem.activity == 'deleted') {
        return <>deleted the flag: {logItem.detail.name}</>
    }
    if (logItem.activity == 'updated') {
        let changes: (string | JSX.Element | null)[] = []

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // feature flag updates have to have a "field" to be described
            }

            changes = changes.concat(featureFlagActionsMapping[change.field](change))
        }

        if (changes.length) {
            return <SentenceList listParts={changes} suffix={<>on {nameOrLinkToFlag(logItem)}</>} />
        }
    }

    return null
}

interface SentenceListProps {
    listParts: (string | JSX.Element | null)[]
    prefix?: string | JSX.Element | null
    suffix?: string | JSX.Element | null
}

function SentenceList({ listParts, prefix = null, suffix = null }: SentenceListProps): JSX.Element {
    return (
        <div className="sentence-list">
            {prefix && <div>{prefix}&nbsp;</div>}
            <>
                {listParts.flatMap((part, index, all) => {
                    const isntFirst = index > 0
                    const isLast = index === all.length - 1
                    const atLeastThree = all.length >= 2
                    return [
                        isntFirst && <div key={`${index}-a`}>,&nbsp;</div>,
                        isLast && atLeastThree && <div key={`${index}-b`}>and&nbsp;</div>,
                        <div key={`${index}-c`}>{part}</div>,
                    ]
                })}
            </>
            {suffix && <div>&nbsp;{suffix}</div>}
        </div>
    )
}
