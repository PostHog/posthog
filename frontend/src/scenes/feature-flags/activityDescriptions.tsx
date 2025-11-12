import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    AnyPropertyFilter,
    FeatureFlagEvaluationRuntime,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    FeatureFlagType,
} from '~/types'

const nameOrLinkToFlag = (id: string | undefined, name: string | null | undefined): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.featureFlag(id)}>{displayName}</Link> : displayName
}

const getRuntimeLabel = (runtime: string): string => {
    switch (runtime) {
        case FeatureFlagEvaluationRuntime.ALL:
            return 'both client and server'
        case FeatureFlagEvaluationRuntime.CLIENT:
            return 'client-side only'
        case FeatureFlagEvaluationRuntime.SERVER:
            return 'server-side only'
        default:
            return runtime
    }
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
                filtersAfter.payloads &&
                    Object.keys(filtersAfter.payloads).forEach((key: string) => {
                        const changedPayload = filtersAfter.payloads?.[key]?.toString() || null
                        changes.push(<SentenceList listParts={[changedPayload]} prefix="changed payload to" />)
                    })

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

                        if ((properties?.length || 0) > 0) {
                            const nonEmptyProperties = properties as AnyPropertyFilter[] // above check ensures this is not null
                            const newButtons =
                                nonEmptyProperties.map((property, idx) => {
                                    return (
                                        <>
                                            {' '}
                                            {idx === 0 && (
                                                <span>
                                                    <strong>{rollout_percentage ?? 100}%</strong> of{' '}
                                                </span>
                                            )}
                                            <PropertyFilterButton key={property.key} item={property} />
                                        </>
                                    )
                                }) || []
                            newButtons[0] = (
                                <>
                                    <span>
                                        <strong>{rollout_percentage ?? 100}%</strong> of{' '}
                                    </span>
                                    <PropertyFilterButton
                                        key={nonEmptyProperties[0].key}
                                        item={nonEmptyProperties[0]}
                                    />
                                </>
                            )
                            groupAdditions.push(...newButtons)
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

        if (filtersBefore?.multivariate?.variants?.length && !filtersAfter?.multivariate?.variants?.length) {
            changes.push(
                <SentenceList
                    key="remove-variants-list"
                    listParts={[
                        <span key="remove-variants">
                            removed{' '}
                            {filtersBefore.multivariate.variants.length === 1 ? 'the last variant' : 'all variants'}
                        </span>,
                    ]}
                />
            )
        } else if (isMultivariateFlag) {
            filtersAfter.payloads &&
                Object.keys(filtersAfter.payloads).forEach((key: string) => {
                    const changedPayload = filtersAfter.payloads?.[key]?.toString() || null
                    changes.push(
                        <SentenceList
                            listParts={[
                                <span key={key} className="highlighted-activity">
                                    {changedPayload}
                                </span>,
                            ]}
                            prefix={
                                <span>
                                    changed payload on <b>variant: {key}</b> to
                                </span>
                            }
                        />
                    )
                })

            // Identify removed variants
            const beforeVariants = new Set((filtersBefore?.multivariate?.variants || []).map((v) => v.key))
            const afterVariants = new Set((filtersAfter?.multivariate?.variants || []).map((v) => v.key))
            const removedVariants = [...beforeVariants].filter((key) => !afterVariants.has(key))

            // First add the rollout percentage changes
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

            // Then add removed variants if any
            if (removedVariants.length > 0) {
                changes.push(
                    <SentenceList
                        listParts={removedVariants.map((key) => (
                            <span key={key} className="highlighted-activity">
                                <strong>{key}</strong>
                            </span>
                        ))}
                        prefix={`removed ${pluralize(
                            removedVariants.length,
                            'variant',
                            undefined,
                            /* includeNumber: */ false
                        )}`}
                    />
                )
            }
        }

        if (changes.length > 0) {
            return { description: changes }
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete(change, logItem) {
        const isDeleted = detectBoolean(change?.after)
        return {
            description: [<>{isDeleted ? 'deleted' : 'un-deleted'}</>],
            suffix: <>{nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>,
        }
    },
    rollout_percentage: function onRolloutPercentage(change) {
        return {
            description: [
                <>
                    changed rollout percentage to <div className="highlighted-activity">{change?.after as string}%</div>
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
        const isEnabled = detectBoolean(change?.after)
        const describeChange: string = isEnabled ? 'enabled' : 'disabled'

        return { description: [<>{describeChange} experience continuity</>] }
    },
    evaluation_runtime: function onEvaluationRuntime(change) {
        const runtimeAfter = change?.after as string
        const runtimeBefore = change?.before as string

        return {
            description: [
                <>
                    changed the evaluation runtime from <strong>{getRuntimeLabel(runtimeBefore)}</strong> to{' '}
                    <strong>{getRuntimeLabel(runtimeAfter)}</strong>
                </>,
            ],
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
    evaluation_tags: function onEvaluationTags(change) {
        const tagsBefore = change?.before as string[]
        const tagsAfter = change?.after as string[]
        const addedTags = tagsAfter.filter((t) => tagsBefore.indexOf(t) === -1)
        const removedTags = tagsBefore.filter((t) => tagsAfter.indexOf(t) === -1)

        const changes: Description[] = []
        if (addedTags.length) {
            changes.push(
                <>
                    added {pluralize(addedTags.length, 'evaluation tag', 'evaluation tags', false)}{' '}
                    <ObjectTags tags={addedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedTags.length) {
            changes.push(
                <>
                    removed {pluralize(removedTags.length, 'evaluation tag', 'evaluation tags', false)}{' '}
                    <ObjectTags tags={removedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }

        return { description: changes }
    },
    // fields that are excluded on the backend
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    updated_at: () => null,
    is_simple_flag: () => null,
    experiment_set: () => null,
    features: () => null,
    usage_dashboard: () => null,
    // TODO: handle activity
    rollback_conditions: () => null,
    performed_rollback: () => null,
    can_edit: () => null,
    analytics_dashboards: () => null,
    has_enriched_analytics: () => null,
    surveys: () => null,
    user_access_level: () => null,
    is_remote_configuration: () => null,
    has_encrypted_payloads: () => null,
    status: () => null,
    version: () => null,
    last_modified_by: () => null,
    last_called_at: () => null,
    _create_in_folder: () => null,
    _should_create_usage_dashboard: () => null,
}

const getActorName = (logItem: ActivityLogItem): JSX.Element => {
    const userName = userNameForLogItem(logItem)
    if (logItem.detail.trigger?.job_type === 'scheduled_change') {
        return (
            <>
                <strong className="ph-no-capture">{userName}</strong>{' '}
                <span className="text-muted">(via scheduled change)</span>
            </>
        )
    }
    return <strong className="ph-no-capture">{userName}</strong>
}

export function flagActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'FeatureFlag') {
        console.error('feature flag describer received a non-feature flag activity')
        return { description: null }
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <SentenceList
                    listParts={[<>created a new feature flag:</>]}
                    prefix={getActorName(logItem)}
                    suffix={<> {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>}
                />
            ),
        }
    }

    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the flag '}
                {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}
            </>
        )

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // feature flag updates have to have a "field" to be described
            }

            const fieldHandler = featureFlagActionsMapping[change.field as keyof FeatureFlagType]
            if (!fieldHandler) {
                console.error({ field: change.field, change }, 'No activity describer found for feature flag field')
            }
            const possibleLogItem = fieldHandler ? fieldHandler(change, logItem) : null
            if (possibleLogItem) {
                const { description, suffix } = possibleLogItem
                if (description) {
                    changes = changes.concat(description)
                }
                if (suffix) {
                    changeSuffix = suffix
                }
            }
        }

        if (changes.length) {
            return {
                description: <SentenceList listParts={changes} prefix={getActorName(logItem)} suffix={changeSuffix} />,
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name))
}
