import { Fragment } from 'react'

import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    ExpandedView,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { FeatureFlagEvaluationRuntime, FeatureFlagFilters, FeatureFlagGroupType, FeatureFlagType } from '~/types'

import { FeatureFlagReleaseConditionsChange } from 'products/feature_flags/frontend/FeatureFlagReleaseConditionsChange'
import {
    ConditionSetAspect,
    ConditionSetChange,
    changedAspects,
    diffReleaseConditionSets,
    rolloutOf,
} from 'products/feature_flags/frontend/releaseConditionsDiff'

const getChangedPayloadKeys = (
    filtersBefore: FeatureFlagFilters | undefined,
    filtersAfter: FeatureFlagFilters
): string[] =>
    Object.keys(filtersAfter.payloads ?? {}).filter((key) => {
        const before = filtersBefore?.payloads?.[key]?.toString() || null
        const after = filtersAfter.payloads?.[key]?.toString() || null
        return before !== after
    })

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

const rolloutLabel = (rollout: number): JSX.Element => <strong className="tabular-nums">{rollout}%</strong>

const conditionSetLabel = (group: FeatureFlagGroupType): JSX.Element => {
    if (group.description) {
        return <strong>"{group.description}"</strong>
    }
    const properties = group.properties ?? []
    if (properties.length === 0) {
        return <strong>{group.aggregation_group_type_index != null ? 'all groups' : 'all users'}</strong>
    }
    return (
        <>
            <PropertyFilterButton item={properties[0]} />
            {properties.length > 1 && (
                <span className="text-muted">
                    {' '}
                    and {properties.length - 1} more{' '}
                    {pluralize(properties.length - 1, 'condition', 'conditions', false)}
                </span>
            )}
        </>
    )
}

const joinInline = (parts: JSX.Element[]): JSX.Element => (
    <>
        {parts.map((part, index) => (
            <Fragment key={index}>
                {index > 0 && (index === parts.length - 1 ? ' and ' : ', ')}
                {part}
            </Fragment>
        ))}
    </>
)

const conditionSetsNoun = (count: number): string => pluralize(count, 'condition set', 'condition sets')

const MAX_DETAILED_SET_CHANGES = 3

const describeConditionSetChanges = (
    filtersBefore: FeatureFlagFilters | undefined,
    filtersAfter: FeatureFlagFilters
): Description[] => {
    const diff = diffReleaseConditionSets(filtersBefore, filtersAfter)
    const added = diff.sets.filter((set) => set.status === 'added')
    const changed = diff.sets.filter((set) => set.status === 'changed')
    const withAspect = (aspect: ConditionSetAspect): ConditionSetChange[] =>
        changed.filter((set) => changedAspects(set).includes(aspect))
    const descriptionOnly = changed.filter((set) => changedAspects(set).join() === 'description')
    const summarize = added.length + changed.length + diff.removed.length > MAX_DETAILED_SET_CHANGES

    // Past the detail limit every part collapses to "<verb> N condition sets"; the expanded view has the rest.
    const listOrCount = <T,>(
        sets: T[],
        verbs: { detail: string; count: string },
        detail: (set: T) => JSX.Element
    ): JSX.Element =>
        summarize ? (
            <>
                {verbs.count} {conditionSetsNoun(sets.length)}
            </>
        ) : (
            <>
                {verbs.detail} {joinInline(sets.map(detail))}
            </>
        )
    const labelOf = (set: ConditionSetChange): JSX.Element => conditionSetLabel(set.group)

    const parts: Description[] = []
    const rolloutChanges = withAspect('rollout')
    const criteriaChanges = withAspect('criteria')
    const variantChanges = withAspect('variant')
    if (rolloutChanges.length) {
        const verbs = { detail: 'changed the rollout for', count: 'changed the rollout for' }
        parts.push(
            listOrCount(rolloutChanges, verbs, (set) => (
                <>
                    {labelOf(set)} from {rolloutLabel(rolloutOf(set.previous ?? set.group))} to{' '}
                    {rolloutLabel(rolloutOf(set.group))}
                </>
            ))
        )
    }
    if (criteriaChanges.length) {
        const verbs = { detail: 'changed the criteria for', count: 'changed the criteria for' }
        parts.push(listOrCount(criteriaChanges, verbs, labelOf))
    }
    if (variantChanges.length) {
        const verbs = { detail: 'changed the variant for', count: 'changed the variant for' }
        parts.push(
            listOrCount(variantChanges, verbs, (set) => (
                <>
                    {labelOf(set)} to <strong>{set.group.variant ?? 'none'}</strong>
                </>
            ))
        )
    }
    if (descriptionOnly.length) {
        parts.push(
            <>
                changed the description of{' '}
                {joinInline(descriptionOnly.map((set) => <>condition set {set.index + 1}</>))}
            </>
        )
    }
    if (added.length) {
        const verbs = {
            detail: added.length === 1 ? 'added a condition set for' : 'added condition sets for',
            count: 'added',
        }
        parts.push(
            listOrCount(added, verbs, (set) => (
                <>
                    {labelOf(set)} at {rolloutLabel(rolloutOf(set.group))}
                </>
            ))
        )
    }
    if (diff.removed.length) {
        parts.push(
            diff.removed.length === 1 && !summarize ? (
                <>removed the condition set for {conditionSetLabel(diff.removed[0].group)}</>
            ) : (
                <>removed {conditionSetsNoun(diff.removed.length)}</>
            )
        )
    }
    if (diff.reordered) {
        parts.push(<>reordered the condition sets</>)
    }
    return parts
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
    filters: function onChangedFilter(change, logItem) {
        const filtersBefore = change?.before as FeatureFlagFilters | undefined
        const filtersAfter = change?.after as FeatureFlagFilters

        const hasConditionSets = Array.isArray(filtersAfter?.groups)
        const isMultivariateFlag = filtersAfter?.multivariate

        const changes: Description[] = []
        let expandedView: ExpandedView | undefined

        if (hasConditionSets) {
            if (!isMultivariateFlag) {
                getChangedPayloadKeys(filtersBefore, filtersAfter).forEach((key) => {
                    const changedPayload = filtersAfter.payloads?.[key]?.toString() || null
                    changes.push(<SentenceList listParts={[changedPayload]} prefix="changed payload to" />)
                })
            }
            changes.push(...describeConditionSetChanges(filtersBefore, filtersAfter))
            expandedView = {
                label: 'Release conditions',
                content: (
                    <FeatureFlagReleaseConditionsChange
                        flagId={logItem?.item_id ?? ''}
                        activityId={logItem?.id ?? logItem?.created_at ?? ''}
                        before={filtersBefore}
                        after={filtersAfter}
                    />
                ),
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
            getChangedPayloadKeys(filtersBefore, filtersAfter).forEach((key) => {
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

            // Only show rollout percentage changes if they actually changed
            const beforeVariantMap = new Map(
                (filtersBefore?.multivariate?.variants || []).map((v) => [v.key, v.rollout_percentage])
            )
            const changedVariants = (filtersAfter.multivariate?.variants || []).filter(
                (v) => beforeVariantMap.get(v.key) !== v.rollout_percentage
            )
            if (changedVariants.length > 0) {
                changes.push(
                    <SentenceList
                        listParts={changedVariants.map((v) => (
                            <div key={v.key} className="highlighted-activity">
                                {v.key}: <strong className="tabular-nums">{v.rollout_percentage}%</strong>
                            </div>
                        ))}
                        prefix="changed the rollout percentage for the variants to"
                    />
                )
            }

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
            return { description: changes, expandedView }
        }

        console.error({ change }, 'could not describe this change')
        return null
    },
    deleted: function onSoftDelete(change, logItem) {
        const isDeleted = detectBoolean(change?.after)
        return {
            description: [<>{isDeleted ? 'deleted' : 'restored'}</>],
            suffix: <>{nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>,
        }
    },
    archived: function onArchived(change, logItem) {
        const isArchived = detectBoolean(change?.after)
        return {
            description: [<>{isArchived ? 'archived' : 'unarchived'}</>],
            suffix: <>{nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}</>,
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
    bucketing_identifier: function onBucketingIdentifier(change) {
        const identifierAfter = change?.after as string
        const identifierBefore = change?.before as string

        const getBucketingLabel = (identifier: string): string => {
            switch (identifier) {
                case 'distinct_id':
                    return 'User'
                case 'device_id':
                    return 'Device'
                default:
                    return identifier || 'User'
            }
        }

        return {
            description: [
                <>
                    changed the bucketing identifier from <strong>{getBucketingLabel(identifierBefore)}</strong> to{' '}
                    <strong>{getBucketingLabel(identifierAfter)}</strong>
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
    evaluation_contexts: function onEvaluationContexts(change) {
        const contextsBefore = (change?.before as string[]) || []
        const contextsAfter = (change?.after as string[]) || []
        const addedContexts = contextsAfter.filter((c) => contextsBefore.indexOf(c) === -1)
        const removedContexts = contextsBefore.filter((c) => contextsAfter.indexOf(c) === -1)

        const changes: Description[] = []
        if (addedContexts.length) {
            changes.push(
                <>
                    added {pluralize(addedContexts.length, 'evaluation context', 'evaluation contexts', false)}{' '}
                    <ObjectTags tags={addedContexts} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedContexts.length) {
            changes.push(
                <>
                    removed {pluralize(removedContexts.length, 'evaluation context', 'evaluation contexts', false)}{' '}
                    <ObjectTags tags={removedContexts} saving={false} style={{ display: 'inline' }} staticOnly />
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
    experiment_set: () => null,
    experiment_set_metadata: () => null,
    features: () => null,
    usage_dashboard: () => null,
    can_edit: () => null,
    has_enriched_analytics: () => null,
    surveys: () => null,
    user_access_level: () => null,
    is_remote_configuration: () => null,
    has_encrypted_payloads: () => null,
    status: () => null,
    version: () => null,
    last_modified_by: () => null,
    last_called_at: () => null,
    is_used_in_replay_settings: () => null,
    _create_in_folder: () => null,
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
        // A referenced cohort's conditions changed: the flag's own fields are untouched
        // (only its version moved), so describe the cohort change instead of a field diff.
        // job_type must stay in sync with COHORT_CONDITIONS_UPDATED_JOB_TYPE in
        // products/feature_flags/backend/flag_version_sync.py.
        if (logItem.detail.trigger?.job_type === 'cohort_conditions_updated') {
            const { cohort_id, cohort_name } = logItem.detail.trigger.payload ?? {}
            return {
                description: (
                    <SentenceList
                        listParts={[
                            <Fragment key="cohort-conditions-updated">
                                changed the conditions of linked cohort{' '}
                                {cohort_id ? (
                                    <Link to={urls.cohort(cohort_id)}>{cohort_name || `#${cohort_id}`}</Link>
                                ) : (
                                    <span>{cohort_name || 'unknown'}</span>
                                )}
                            </Fragment>,
                        ]}
                        prefix={getActorName(logItem)}
                        suffix={
                            <>
                                on {asNotification && ' the flag '}
                                {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}
                            </>
                        }
                    />
                ),
            }
        }
        // A flag this one depends on changed its definition: same story as above, only
        // this flag's version moved. job_type must stay in sync with
        // FLAG_DEPENDENCY_UPDATED_JOB_TYPE in
        // products/feature_flags/backend/flag_version_sync.py.
        if (logItem.detail.trigger?.job_type === 'flag_dependency_updated') {
            const { flag_id, flag_key } = logItem.detail.trigger.payload ?? {}
            return {
                description: (
                    <SentenceList
                        listParts={[
                            <Fragment key="flag-dependency-updated">
                                changed the definition of linked flag{' '}
                                {flag_id ? (
                                    <Link to={urls.featureFlag(flag_id)}>{flag_key || `#${flag_id}`}</Link>
                                ) : (
                                    <span>{flag_key || 'unknown'}</span>
                                )}
                            </Fragment>,
                        ]}
                        prefix={getActorName(logItem)}
                        suffix={
                            <>
                                on {asNotification && ' the flag '}
                                {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}
                            </>
                        }
                    />
                ),
            }
        }
        let changes: Description[] = []
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the flag '}
                {nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name)}
            </>
        )
        let expandedView: ExpandedView | undefined

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
                const { description, suffix, expandedView: view } = possibleLogItem
                if (description) {
                    changes = changes.concat(description)
                }
                if (suffix) {
                    changeSuffix = suffix
                }
                if (view) {
                    expandedView = view
                }
            }
        }

        if (changes.length) {
            return {
                description: <SentenceList listParts={changes} prefix={getActorName(logItem)} suffix={changeSuffix} />,
                expandedView,
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToFlag(logItem?.item_id, logItem?.detail.name))
}
