import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ChangeDescriptions, FeatureFlagFilters, FeatureFlagGroupType, FeatureFlagType } from '~/types'
import React from 'react'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { pluralize } from 'lib/utils'

const nameOrLinkToFlag = (item: ActivityLogItem): string | JSX.Element => {
    const name = item.detail.name || '(empty string)'
    return item.item_id ? <Link to={urls.featureFlag(item.item_id)}>{name}</Link> : name
}

const featureFlagActionsMapping: Record<keyof FeatureFlagType, (change?: ActivityChange) => ChangeDescriptions | null> =
    {
        name: function onName(change) {
            return {
                descriptions: [
                    <>
                        changed the description to <strong>"{change?.after}"</strong>
                    </>,
                ],
                bareName: false,
            }
        },
        active: function onActive(change) {
            let isActive: boolean = !!change?.after
            if (typeof change?.after === 'string') {
                isActive = change?.after.toLowerCase() === 'true'
            }
            const describeChange: string = isActive ? 'enabled' : 'disabled'

            return { descriptions: [<>{describeChange}</>], bareName: true }
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
                            <SentenceList
                                listParts={groupAdditions}
                                prefix="changed the filter conditions to apply to"
                            />
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
                return { descriptions: changes, bareName: false }
            }

            console.error({ change }, 'could not describe this change')
            return null
        },
        deleted: function onSoftDelete() {
            return { descriptions: [<>deleted</>], bareName: true }
        },
        rollout_percentage: function onRolloutPercentage(change) {
            return {
                descriptions: [
                    <>
                        changed rollout percentage to <div className="highlighted-activity">{change?.after}%</div>
                    </>,
                ],
                bareName: false,
            }
        },
        key: function onKey(change) {
            return { descriptions: [<>changed flag key from ${change?.before}</>], bareName: false }
        },
        ensure_experience_continuity: function onExperienceContinuity(change) {
            let isEnabled: boolean = !!change?.after
            if (typeof change?.after === 'string') {
                isEnabled = change?.after.toLowerCase() === 'true'
            }
            const describeChange: string = isEnabled ? 'enabled' : 'disabled'

            return { descriptions: [<>{describeChange}</>], bareName: true }
        },
        // fields that are excluded on the backend
        id: () => null,
        created_at: () => null,
        created_by: () => null,
        is_simple_flag: () => null,
    }

export function flagActivityDescriber(logItem: ActivityLogItem): string | JSX.Element | null {
    if (logItem.scope != 'FeatureFlag') {
        console.error('feature flag describer received a non-feature flag activity')
        return null
    }

    if (logItem.activity == 'created') {
        return <>created the flag: {nameOrLinkToFlag(logItem)}</>
    }
    if (logItem.activity == 'deleted') {
        return <>deleted the flag: {logItem.detail.name}</>
    }
    if (logItem.activity == 'updated') {
        const changes: ChangeDescriptions = { descriptions: [], bareName: false }

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // feature flag updates have to have a "field" to be described
            }

            const nextChange: ChangeDescriptions | null = featureFlagActionsMapping[change.field](change)
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
                            {sayOn} {nameOrLinkToFlag(logItem)}
                        </>
                    }
                />
            )
        }
    }

    return null
}

interface SentenceListProps {
    listParts: (string | JSX.Element | null)[]
    prefix?: string | JSX.Element | null
    suffix?: string | JSX.Element | null
}

// TODO this should be a component. and needs the height of parts sorting out
export function SentenceList({ listParts, prefix = null, suffix = null }: SentenceListProps): JSX.Element {
    return (
        <div className="sentence-list">
            {prefix && <div className="sentence-part">{prefix}&#32;</div>}
            <>
                {listParts
                    .filter((part) => !!part)
                    .flatMap((part, index, all) => {
                        const isntFirst = index > 0
                        const isLast = index === all.length - 1
                        const atLeastThree = all.length >= 2
                        return [
                            isntFirst && (
                                <div className="sentence-part" key={`${index}-a`}>
                                    ,&#32;
                                </div>
                            ),
                            isLast && atLeastThree && (
                                <div className="sentence-part" key={`${index}-b`}>
                                    and&#32;
                                </div>
                            ),
                            <div className="sentence-part" key={`${index}-c`}>
                                {part}
                            </div>,
                        ]
                    })}
            </>
            {suffix && <div className="sentence-part">&#32;{suffix}</div>}
        </div>
    )
}
