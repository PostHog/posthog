import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { FeatureFlagFilters, FeatureFlagGroupType, FeatureFlagType } from '~/types'
import React from 'react'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { pluralize } from 'lib/utils'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

const nameOrLinkToFlag = (id: string | undefined, name: string | null | undefined): string | JSX.Element => {
    // detail.name
    // item_id
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.featureFlag(id)}>{displayName}</Link> : displayName
}

const featureFlagActionsMapping: Record<
    keyof FeatureFlagType,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    name: function onName() {
        return {
            description: [<>changed the description</>],
        }
    },
    active: function onActive(change, logItem) {
        let isActive: boolean = !!change?.after
        if (typeof change?.after === 'string') {
            isActive = change?.after.toLowerCase() === 'true'
        }
        const describeChange: string = isActive ? 'enabled' : 'disabled'

        return {
            description: [<>{describeChange}</>],
            suffix: <>{nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>,
        }
    },
    filters: function onChangedFilter(change) {
        const filtersBefore = change?.before as FeatureFlagFilters
        const filtersAfter = change?.after as FeatureFlagFilters

        const isBooleanValueFlag = Array.isArray(filtersAfter?.groups)
        const isMultivariateFlag = filtersAfter?.multivariate

        const changes: Description[] = []

        if (isBooleanValueFlag) {
            if (
                filtersAfter.groups.length === 0 ||
                !filtersAfter.groups.some((group) => group.rollout_percentage !== 0)
            ) {
                // there are no rollout groups or all are at 0%
                changes.push(<>changed the filter conditions to apply to no users</>)
            } else {
                const groupAdditions: (string | JSX.Element | null)[] = []
                const groupRemovals: (string | JSX.Element | null)[] = []

                filtersAfter.groups
                    .filter((groupAfter, index) => {
                        const groupBefore = filtersBefore?.groups?.[index]
                        // only keep changes with no "before" state, or those where before and after are different
                        return !groupBefore || JSON.stringify(groupBefore) !== JSON.stringify(groupAfter)
                    })
                    .forEach((groupAfter: FeatureFlagGroupType) => {
                        const { properties, rollout_percentage = null } = groupAfter

                        if (properties?.length > 0) {
                            groupAdditions.push(
                                <>
                                    <span>
                                        <strong>{rollout_percentage ?? 100}%</strong> of
                                    </span>
                                    <PropertyFiltersDisplay
                                        filters={properties}
                                        style={{
                                            display: 'inline-block',
                                            marginLeft: '0.3rem',
                                            marginBottom: 0,
                                        }}
                                    />
                                </>
                            )
                        } else {
                            groupAdditions.push(
                                <>
                                    <strong>{rollout_percentage ?? 100}%</strong> of <strong>all users</strong>
                                </>
                            )
                        }
                    })

                if (groupAdditions.length) {
                    changes.push(
                        <SentenceList listParts={groupAdditions} prefix="changed the filter conditions to apply to" />
                    )
                }

                const removedGroups = (filtersBefore?.groups || []).filter((_, index) => {
                    const groupAfter = filtersAfter?.groups?.[index]
                    // only keep changes with no "after" state, they've been removed
                    return !groupAfter
                })

                if (removedGroups.length) {
                    groupRemovals.push(
                        <>
                            <strong>removed </strong>{' '}
                            {pluralize(removedGroups.length, 'release condition', 'release conditions')}
                        </>
                    )
                }

                if (groupRemovals.length) {
                    changes.push(<SentenceList listParts={groupRemovals} />)
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
            return { description: changes }
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete(change, logItem) {
        const isDeleted: boolean = !!change?.after
        return {
            description: [<>{isDeleted ? 'deleted' : 'un-deleted'}</>],
            suffix: <>{nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>,
        }
    },
    rollout_percentage: function onRolloutPercentage(change) {
        return {
            description: [
                <>
                    changed rollout percentage to <div className="highlighted-activity">{change?.after}%</div>
                </>,
            ],
        }
    },
    key: function onKey(change, logItem) {
        const changeBefore = change?.before as string
        const changeAfter = change?.after as string
        return {
            description: [<>changed flag key on {changeBefore} to</>],
            suffix: <>{nameOrLinkToFlag(logItem?.item_id, changeAfter)}</>,
        }
    },
    ensure_experience_continuity: function onExperienceContinuity(change) {
        let isEnabled: boolean = !!change?.after
        if (typeof change?.after === 'string') {
            isEnabled = change?.after.toLowerCase() === 'true'
        }
        const describeChange: string = isEnabled ? 'enabled' : 'disabled'

        return { description: [<>{describeChange} experience continuity</>] }
    },
    // fields that are excluded on the backend
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    is_simple_flag: () => null,
    experiment_set: () => null,
}

export function flagActivityDescriber(logItem: ActivityLogItem): HumanizedChange {
    if (logItem.scope != 'FeatureFlag') {
        console.error('feature flag describer received a non-feature flag activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        return { description: <>created {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</> }
    }
    if (logItem.activity == 'deleted') {
        return { description: <>deleted {logItem.detail.name}</> }
    }
    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let changeSuffix: Description = <>on {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // feature flag updates have to have a "field" to be described
            }

            const { description, suffix } = featureFlagActionsMapping[change.field](change, logItem)
            if (description) {
                changes = changes.concat(description)
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
                        prefix={
                            <>
                                <strong>{logItem.user.first_name}</strong>
                            </>
                        }
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    return { description: null }
}
