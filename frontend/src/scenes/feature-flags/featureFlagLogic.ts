import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, forms, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { sum, toParams } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { NEW_EARLY_ACCESS_FEATURE } from 'scenes/early-access-features/earlyAccessFeatureLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { Scene } from 'scenes/sceneTypes'
import { NEW_SURVEY, NewSurvey } from 'scenes/surveys/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
    AvailableFeature,
    Breadcrumb,
    CohortType,
    DashboardBasicType,
    EarlyAccessFeatureType,
    FeatureFlagGroupType,
    FeatureFlagRollbackConditions,
    FeatureFlagType,
    FilterType,
    InsightModel,
    InsightType,
    MultivariateFlagOptions,
    MultivariateFlagVariant,
    NewEarlyAccessFeatureType,
    OrganizationFeatureFlag,
    PropertyFilterType,
    PropertyOperator,
    RolloutConditionType,
    ScheduledChangeOperationType,
    ScheduledChangeType,
    Survey,
    SurveyQuestionType,
    UserBlastRadiusType,
} from '~/types'

import { organizationLogic } from '../organizationLogic'
import { teamLogic } from '../teamLogic'
import type { featureFlagLogicType } from './featureFlagLogicType'
import { featureFlagPermissionsLogic } from './featureFlagPermissionsLogic'

const getDefaultRollbackCondition = (): FeatureFlagRollbackConditions => ({
    operator: 'gt',
    threshold_type: RolloutConditionType.Sentry,
    threshold: 50,
    threshold_metric: {
        ...cleanFilters({
            insight: InsightType.TRENDS,
            date_from: dayjs().subtract(7, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
        }),
    },
})

const NEW_FLAG: FeatureFlagType = {
    id: null,
    created_at: null,
    key: '',
    name: '',
    filters: {
        groups: [{ properties: [], rollout_percentage: undefined, variant: null }],
        multivariate: null,
        payloads: {},
    },
    deleted: false,
    active: true,
    created_by: null,
    is_simple_flag: false,
    rollout_percentage: null,
    ensure_experience_continuity: false,
    experiment_set: null,
    features: [],
    rollback_conditions: [],
    surveys: null,
    performed_rollback: false,
    can_edit: true,
    tags: [],
}
const NEW_VARIANT = {
    key: '',
    name: '',
    rollout_percentage: 0,
}
const EMPTY_MULTIVARIATE_OPTIONS: MultivariateFlagOptions = {
    variants: [
        {
            key: '',
            name: '',
            rollout_percentage: 100,
        },
    ],
}

/** Check whether a string is a valid feature flag key. If not, a reason string is returned - otherwise undefined. */
export function validateFeatureFlagKey(key: string): string | undefined {
    return !key
        ? 'You need to set a key'
        : !key.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
        ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
        : undefined
}

export interface FeatureFlagLogicProps {
    id: number | 'new' | 'link' | 'schedule'
}

// KLUDGE: Payloads are returned in a <variant-key>: <payload> mapping.
// This doesn't work for forms because variant-keys can be updated too which would invalidate the dictionary entry.
// If a multivariant flag is returned, the payload dictionary will be transformed to be <variant-key-index>: <payload>
const variantKeyToIndexFeatureFlagPayloads = (flag: FeatureFlagType): FeatureFlagType => {
    if (!flag.filters.multivariate) {
        return flag
    }

    const newPayloads = {}
    flag.filters.multivariate?.variants.forEach((variant, index) => {
        newPayloads[index] = flag.filters.payloads?.[variant.key]
    })
    return {
        ...flag,
        filters: {
            ...flag.filters,
            payloads: newPayloads,
        },
    }
}

const indexToVariantKeyFeatureFlagPayloads = (flag: Partial<FeatureFlagType>): Partial<FeatureFlagType> => {
    if (flag.filters?.multivariate) {
        const newPayloads = {}
        flag.filters?.multivariate?.variants.forEach(({ key }, index) => {
            const payload = flag.filters?.payloads?.[index]
            if (payload) {
                newPayloads[key] = payload
            }
        })
        return {
            ...flag,
            filters: {
                ...flag.filters,
                payloads: newPayloads,
            },
        }
    }
    if (flag.filters && !flag.filters.multivariate) {
        let cleanedPayloadValue = {}
        if (flag.filters.payloads?.['true']) {
            cleanedPayloadValue = { true: flag.filters.payloads['true'] }
        }
        return {
            ...flag,
            filters: {
                ...flag.filters,
                payloads: cleanedPayloadValue,
            },
        }
    }
    return flag
}

export const featureFlagLogic = kea<featureFlagLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagLogic']),
    props({} as FeatureFlagLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect((props: FeatureFlagLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'groupsTaxonomicTypes', 'aggregationLabel'],
            userLogic,
            ['hasAvailableFeature'],
            dashboardsLogic,
            ['dashboards'],
            organizationLogic,
            ['currentOrganization'],
            enabledFeaturesLogic,
            ['featureFlags as enabledFeatures'],
        ],
        actions: [
            newDashboardLogic({ featureFlagId: typeof props.id === 'number' ? props.id : undefined }),
            ['submitNewDashboardSuccessWithResult'],
        ],
    })),
    actions({
        setFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        setFeatureFlagMissing: true,
        addConditionSet: true,
        addRollbackCondition: true,
        setAggregationGroupTypeIndex: (value: number | null) => ({ value }),
        removeConditionSet: (index: number) => ({ index }),
        removeRollbackCondition: (index: number) => ({ index }),
        duplicateConditionSet: (index: number) => ({ index }),
        updateConditionSet: (
            index: number,
            newRolloutPercentage?: number,
            newProperties?: AnyPropertyFilter[],
            newVariant?: string | null
        ) => ({
            index,
            newRolloutPercentage,
            newProperties,
            newVariant,
        }),
        deleteFeatureFlag: (featureFlag: Partial<FeatureFlagType>) => ({ featureFlag }),
        setMultivariateEnabled: (enabled: boolean) => ({ enabled }),
        setMultivariateOptions: (multivariateOptions: MultivariateFlagOptions | null) => ({ multivariateOptions }),
        addVariant: true,
        duplicateVariant: (index: number) => ({ index }),
        removeVariant: (index: number) => ({ index }),
        editFeatureFlag: (editing: boolean) => ({ editing }),
        distributeVariantsEqually: true,
        loadInsightAtIndex: (index: number, filters: Partial<FilterType>) => ({ index, filters }),
        setInsightResultAtIndex: (index: number, average: number) => ({ index, average }),
        loadAllInsightsForFlag: true,
        setAffectedUsers: (index: number, count?: number) => ({ index, count }),
        setTotalUsers: (count: number) => ({ count }),
        triggerFeatureFlagUpdate: (payload: Partial<FeatureFlagType>) => ({ payload }),
        generateUsageDashboard: true,
        enrichUsageDashboard: true,
        setFeatureFlagId: (id: number | null) => ({ id }),
        setCopyDestinationProject: (id: number | null) => ({ id }),
        setScheduleDateMarker: (dateMarker: any) => ({ dateMarker }),
        setScheduledChangeOperation: (changeType: string | null) => ({ changeType }),
    }),
    forms(({ actions, values }) => ({
        featureFlag: {
            defaults: { ...NEW_FLAG } as FeatureFlagType,
            errors: ({ key, filters }) => {
                return {
                    key: validateFeatureFlagKey(key),
                    filters: {
                        multivariate: {
                            variants: filters?.multivariate?.variants?.map(
                                ({ key: variantKey }: MultivariateFlagVariant) => ({
                                    key: validateFeatureFlagKey(variantKey),
                                })
                            ),
                        },
                        groups: values.propertySelectErrors as DeepPartialMap<
                            FeatureFlagGroupType,
                            ValidationErrorType
                        >[],
                    },
                }
            },
            submit: (featureFlag) => {
                actions.saveFeatureFlag(featureFlag)
            },
        },
    })),
    reducers({
        featureFlag: [
            { ...NEW_FLAG } as FeatureFlagType,
            {
                setFeatureFlag: (_, { featureFlag }) => {
                    if (featureFlag.filters.groups) {
                        const groups = featureFlag.filters.groups.map((group) => {
                            if (group.properties) {
                                return {
                                    ...group,
                                    properties: convertPropertyGroupToProperties(
                                        group.properties
                                    ) as AnyPropertyFilter[],
                                }
                            }
                            return group
                        })
                        return { ...featureFlag, filters: { ...featureFlag?.filters, groups } }
                    }
                    return featureFlag
                },
                addConditionSet: (state) => {
                    if (!state) {
                        return state
                    }
                    const groups = [
                        ...(state?.filters?.groups || []),
                        { properties: [], rollout_percentage: undefined, variant: null },
                    ]
                    return { ...state, filters: { ...state.filters, groups } }
                },
                addRollbackCondition: (state) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        rollback_conditions: [...state.rollback_conditions, getDefaultRollbackCondition()],
                    }
                },
                removeRollbackCondition: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const rollback_conditions = [...state.rollback_conditions]
                    rollback_conditions.splice(index, 1)
                    return { ...state, rollback_conditions: rollback_conditions }
                },
                updateConditionSet: (state, { index, newRolloutPercentage, newProperties, newVariant }) => {
                    if (!state) {
                        return state
                    }

                    const groups = [...(state?.filters?.groups || [])]
                    if (newRolloutPercentage !== undefined) {
                        groups[index] = { ...groups[index], rollout_percentage: newRolloutPercentage }
                    }

                    if (newProperties !== undefined) {
                        groups[index] = { ...groups[index], properties: newProperties }
                    }

                    if (newVariant !== undefined) {
                        groups[index] = { ...groups[index], variant: newVariant }
                    }

                    return { ...state, filters: { ...state.filters, groups } }
                },
                removeConditionSet: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const groups = [...state.filters.groups]
                    groups.splice(index, 1)
                    return { ...state, filters: { ...state.filters, groups } }
                },
                duplicateConditionSet: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const groups = state.filters.groups.concat([state.filters.groups[index]])
                    return { ...state, filters: { ...state.filters, groups } }
                },
                setMultivariateOptions: (state, { multivariateOptions }) => {
                    if (!state) {
                        return state
                    }
                    return { ...state, filters: { ...state.filters, multivariate: multivariateOptions } }
                },
                addVariant: (state) => {
                    if (!state) {
                        return state
                    }
                    const variants = [...(state.filters.multivariate?.variants || [])]
                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            multivariate: {
                                ...(state.filters.multivariate || {}),
                                variants: [...variants, NEW_VARIANT],
                            },
                        },
                    }
                },
                removeVariant: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const variants = [...(state.filters.multivariate?.variants || [])]
                    variants.splice(index, 1)
                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            multivariate: {
                                ...state.filters.multivariate,
                                variants,
                            },
                        },
                    }
                },
                distributeVariantsEqually: (state) => {
                    // Adjust the variants to be as evenly distributed as possible,
                    // taking integer rounding into account
                    if (!state) {
                        return state
                    }
                    const variants = [...(state.filters.multivariate?.variants || [])]
                    const numVariants = variants.length
                    if (numVariants > 0 && numVariants <= 100) {
                        const percentageRounded = Math.round(100 / numVariants)
                        const totalRounded = percentageRounded * numVariants
                        const delta = totalRounded - 100
                        variants.forEach((variant, index) => {
                            variants[index] = { ...variant, rollout_percentage: percentageRounded }
                        })
                        // Apply the rounding error to the last index
                        variants[numVariants - 1] = {
                            ...variants[numVariants - 1],
                            rollout_percentage: percentageRounded - delta,
                        }
                    }
                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            multivariate: {
                                ...state.filters.multivariate,
                                variants,
                            },
                        },
                    }
                },
                setAggregationGroupTypeIndex: (state, { value }) => {
                    if (!state || state.filters.aggregation_group_type_index == value) {
                        return state
                    }

                    const originalRolloutPercentage = state.filters.groups[0].rollout_percentage

                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            aggregation_group_type_index: value,
                            // :TRICKY: We reset property filters after changing what you're aggregating by.
                            groups: [{ properties: [], rollout_percentage: originalRolloutPercentage, variant: null }],
                        },
                    }
                },
                createEarlyAccessFeatureSuccess: (state, { newEarlyAccessFeature }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        features: [...(state.features || []), newEarlyAccessFeature],
                    }
                },
                createSurveySuccess: (state, { newSurvey }) => {
                    if (!state) {
                        return state
                    }
                    return {
                        ...state,
                        surveys: [...(state.surveys || []), newSurvey],
                    }
                },
                setFeatureFlagId: (state, { id }) => ({ ...state, id }),
            },
        ],
        featureFlagMissing: [false, { setFeatureFlagMissing: () => true }],
        isEditingFlag: [
            false,
            {
                editFeatureFlag: (_, { editing }) => editing,
            },
        ],
        insightRollingAverages: [
            {},
            {
                setInsightResultAtIndex: (state, { index, average }) => ({
                    ...state,
                    [`${index}`]: average,
                }),
            },
        ],
        affectedUsers: [
            { 0: -1 },
            {
                setAffectedUsers: (state, { index, count }) => ({
                    ...state,
                    [index]: count,
                }),
                resetFeatureFlag: () => ({ 0: -1 }),
                loadFeatureFlag: () => ({ 0: -1 }),
            },
        ],
        totalUsers: [
            null as number | null,
            {
                setTotalUsers: (_, { count }) => count,
            },
        ],
        copyDestinationProject: [
            null as number | null,
            {
                setCopyDestinationProject: (_, { id }) => id,
            },
        ],
        scheduleDateMarker: [
            null as any,
            {
                setScheduleDateMarker: (_, { dateMarker }) => dateMarker,
            },
        ],
        scheduledChangeOperation: [
            ScheduledChangeOperationType.AddReleaseCondition as string | null,
            {
                setScheduledChangeOperation: (_, { changeType }) => changeType,
            },
        ],
    }),
    loaders(({ values, props, actions }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                if (props.id && props.id !== 'new' && props.id !== 'link' && props.id !== 'schedule') {
                    try {
                        const retrievedFlag: FeatureFlagType = await api.featureFlags.get(props.id)
                        return variantKeyToIndexFeatureFlagPayloads(retrievedFlag)
                    } catch (e) {
                        actions.setFeatureFlagMissing()
                        throw e
                    }
                }
                return NEW_FLAG
            },
            saveFeatureFlag: async (updatedFlag: Partial<FeatureFlagType>) => {
                const { created_at, id, ...flag } = updatedFlag

                const preparedFlag = indexToVariantKeyFeatureFlagPayloads(flag)

                try {
                    let savedFlag: FeatureFlagType
                    if (!updatedFlag.id) {
                        savedFlag = await api.create(`api/projects/${values.currentTeamId}/feature_flags`, preparedFlag)
                        if (values.roleBasedAccessEnabled && savedFlag.id) {
                            featureFlagPermissionsLogic({ flagId: null })?.actions.addAssociatedRoles(savedFlag.id)
                        }
                    } else {
                        savedFlag = await api.update(
                            `api/projects/${values.currentTeamId}/feature_flags/${updatedFlag.id}`,
                            preparedFlag
                        )
                    }

                    return variantKeyToIndexFeatureFlagPayloads(savedFlag)
                } catch (error: any) {
                    if (error.code === 'behavioral_cohort_found' || error.code === 'cohort_does_not_exist') {
                        eventUsageLogic.actions.reportFailedToCreateFeatureFlagWithCohort(error.code, error.detail)
                    }
                    throw error
                }
            },
        },
        relatedInsights: [
            [] as InsightModel[],
            {
                loadRelatedInsights: async () => {
                    if (props.id && props.id !== 'new' && values.featureFlag.key) {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/insights/?feature_flag=${values.featureFlag.key}&order=-created_at`
                        )
                        return response.results
                    }
                    return []
                },
            },
        ],
        sentryStats: [
            {} as { total_count?: number; sentry_integration_enabled?: number },
            {
                loadSentryStats: async () => {
                    return await api.get(`api/sentry_stats/`)
                },
            },
        ],
        // used to generate a new early access feature
        // but all subsequent operations after generation should occur via the earlyAccessFeatureLogic
        newEarlyAccessFeature: [
            null as EarlyAccessFeatureType | null,
            {
                createEarlyAccessFeature: async () => {
                    const newEarlyAccessFeature = {
                        ...NEW_EARLY_ACCESS_FEATURE,
                        name: `Early access: ${values.featureFlag.key}`,
                        feature_flag_id: values.featureFlag.id,
                    }
                    return await api.earlyAccessFeatures.create(newEarlyAccessFeature as NewEarlyAccessFeatureType)
                },
            },
        ],
        // used to generate a new survey
        // but all subsequent operations after generation should occur via the surveyLogic
        newSurvey: [
            null as Survey | null,
            {
                createSurvey: async () => {
                    const newSurvey = {
                        ...NEW_SURVEY,
                        name: `Survey: ${values.featureFlag.key}`,
                        linked_flag_id: values.featureFlag.id,
                        questions: [
                            {
                                type: SurveyQuestionType.Open,
                                question: `What do you think of ${values.featureFlag.key}?`,
                            },
                        ],
                    }
                    return await api.surveys.create(newSurvey as NewSurvey)
                },
            },
        ],
        newCohort: [
            null as CohortType | null,
            {
                createStaticCohort: async () => {
                    if (props.id && props.id !== 'new' && props.id !== 'link' && props.id !== 'schedule') {
                        return (await api.featureFlags.createStaticCohort(props.id)).cohort
                    }
                    return null
                },
            },
        ],
        projectsWithCurrentFlag: {
            __default: [] as OrganizationFeatureFlag[],
            loadProjectsWithCurrentFlag: async () => {
                const orgId = values.currentOrganization?.id
                const flagKey = values.featureFlag.key

                const projects = await api.organizationFeatureFlags.get(orgId, flagKey)

                // Put current project first
                const currentProjectIdx = projects.findIndex((p) => p.team_id === values.currentTeamId)
                if (currentProjectIdx) {
                    const [currentProject] = projects.splice(currentProjectIdx, 1)
                    const sortedProjects = [currentProject, ...projects]
                    return sortedProjects
                }
                return projects
            },
        },
        featureFlagCopy: {
            copyFlag: async () => {
                const orgId = values.currentOrganization?.id
                const featureFlagKey = values.featureFlag.key
                const { copyDestinationProject, currentTeamId } = values

                if (currentTeamId && copyDestinationProject) {
                    return await api.organizationFeatureFlags.copy(orgId, {
                        feature_flag_key: featureFlagKey,
                        from_project: currentTeamId,
                        target_project_ids: [copyDestinationProject],
                    })
                }
            },
        },
        scheduledChanges: {
            __default: [] as ScheduledChangeType[],
            loadScheduledChanges: async () => {
                const { currentTeamId } = values
                if (currentTeamId) {
                    const response = await api.featureFlags.getScheduledChanges(currentTeamId, values.featureFlag.id)
                    return response.results || []
                }
            },
        },
        scheduledChange: {
            __default: {} as ScheduledChangeType,
            createScheduledChange: async () => {
                const { featureFlag, scheduledChangeOperation, scheduleDateMarker, currentTeamId } = values

                const fields = {
                    [ScheduledChangeOperationType.UpdateStatus]: 'active',
                    [ScheduledChangeOperationType.AddReleaseCondition]: 'filters',
                }

                if (currentTeamId && scheduledChangeOperation) {
                    const data = {
                        record_id: values.featureFlag.id,
                        model_name: 'FeatureFlag',
                        payload: {
                            operation: scheduledChangeOperation,
                            value: featureFlag[fields[scheduledChangeOperation]],
                        },
                        scheduled_at: scheduleDateMarker.toISOString(),
                    }

                    return await api.featureFlags.createScheduledChange(currentTeamId, data)
                }
            },
            deleteScheduledChange: async (scheduledChangeId) => {
                const { currentTeamId } = values
                if (currentTeamId) {
                    return await api.featureFlags.deleteScheduledChange(currentTeamId, scheduledChangeId)
                }
            },
        },
    })),
    listeners(({ actions, values, props }) => ({
        submitNewDashboardSuccessWithResult: async ({ result }) => {
            await api.update(`api/projects/${values.currentTeamId}/feature_flags/${values.featureFlag.id}`, {
                analytics_dashboards: [result.id],
            })
        },
        generateUsageDashboard: async () => {
            if (props.id) {
                await api.create(`api/projects/${values.currentTeamId}/feature_flags/${props.id}/dashboard`)
                actions.loadFeatureFlag()
            }
        },
        enrichUsageDashboard: async (_, breakpoint) => {
            if (props.id) {
                await breakpoint(1000) // in ms
                await api.create(
                    `api/projects/${values.currentTeamId}/feature_flags/${props.id}/enrich_usage_dashboard`
                )
            }
        },
        submitFeatureFlagFailure: async () => {
            // When errors occur, scroll to the error, but wait for errors to be set in the DOM first
            setTimeout(
                () => document.querySelector(`.Field--error`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }),
                1
            )
        },
        saveFeatureFlagSuccess: ({ featureFlag }) => {
            lemonToast.success('Feature flag saved')
            featureFlagsLogic.findMounted()?.actions.updateFlag(featureFlag)
            featureFlag.id && router.actions.replace(urls.featureFlag(featureFlag.id))
            actions.editFeatureFlag(false)
        },
        deleteFeatureFlag: async ({ featureFlag }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentTeamId}/feature_flags`,
                object: { name: featureFlag.key, id: featureFlag.id },
                callback: () => {
                    featureFlag.id && featureFlagsLogic.findMounted()?.actions.deleteFlag(featureFlag.id)
                    featureFlagsLogic.findMounted()?.actions.loadFeatureFlags()
                    router.actions.push(urls.featureFlags())
                },
            })
        },
        setMultivariateEnabled: async ({ enabled }) => {
            if (enabled) {
                actions.setMultivariateOptions(EMPTY_MULTIVARIATE_OPTIONS)
            } else {
                actions.setMultivariateOptions(null)
            }
        },
        loadFeatureFlagSuccess: async () => {
            actions.loadRelatedInsights()
            actions.loadAllInsightsForFlag()
        },
        loadInsightAtIndex: async ({ index, filters }) => {
            if (filters) {
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/insights/trend/?${toParams(
                        filterTrendsClientSideParams(filters)
                    )}`
                )
                const counts = response.result?.[0]?.data
                const avg = Math.round(sum(counts) / 7)
                actions.setInsightResultAtIndex(index, avg)
            }
        },
        loadAllInsightsForFlag: () => {
            values.featureFlag.rollback_conditions?.forEach((condition, index) => {
                if (condition.threshold_metric) {
                    actions.loadInsightAtIndex(index, condition.threshold_metric)
                }
            })
        },
        addRollbackCondition: () => {
            const index = values.featureFlag.rollback_conditions.length - 1
            actions.loadInsightAtIndex(
                index,
                values.featureFlag.rollback_conditions[index].threshold_metric as FilterType
            )
        },
        updateConditionSet: async ({ index, newProperties }, breakpoint) => {
            if (newProperties) {
                // properties have changed, so we'll have to re-fetch affected users
                actions.setAffectedUsers(index, undefined)
            }

            if (
                !newProperties ||
                newProperties.some(
                    (property) =>
                        property.value === null ||
                        property.value === undefined ||
                        (Array.isArray(property.value) && property.value.length === 0)
                )
            ) {
                return
            }

            await breakpoint(1000) // in ms

            const response = await api.create(`api/projects/${values.currentTeamId}/feature_flags/user_blast_radius`, {
                condition: { properties: newProperties },
                group_type_index: values.featureFlag?.filters?.aggregation_group_type_index ?? null,
            })
            actions.setAffectedUsers(index, response.users_affected)
            actions.setTotalUsers(response.total_users)
        },
        addConditionSet: () => {
            actions.setAffectedUsers(values.featureFlag.filters.groups.length - 1, -1)
        },
        editFeatureFlag: async ({ editing }) => {
            if (!editing) {
                return
            }

            const usersAffected: Promise<UserBlastRadiusType>[] = []

            values.featureFlag?.filters?.groups?.forEach((condition, index) => {
                actions.setAffectedUsers(index, undefined)

                const properties = condition.properties
                if (
                    !properties ||
                    properties?.length === 0 ||
                    properties.some(
                        (property) =>
                            property.value === null ||
                            property.value === undefined ||
                            (Array.isArray(property.value) && property.value.length === 0)
                    )
                ) {
                    // don't compute for full rollouts or empty conditions
                    usersAffected.push(Promise.resolve({ users_affected: -1, total_users: -1 }))
                } else {
                    const responsePromise = api.create(
                        `api/projects/${values.currentTeamId}/feature_flags/user_blast_radius`,
                        {
                            condition,
                            group_type_index: values.featureFlag?.filters?.aggregation_group_type_index ?? null,
                        }
                    )

                    usersAffected.push(responsePromise)
                }
            })

            const results = await Promise.all(usersAffected)
            // Create action for all users affected
            results.forEach((result, index) => {
                actions.setAffectedUsers(index, result.users_affected)
                if (result.total_users !== -1) {
                    actions.setTotalUsers(result.total_users)
                }
            })
        },
        triggerFeatureFlagUpdate: async ({ payload }) => {
            if (values.featureFlag) {
                const updatedFlag = await api.update(
                    `api/projects/${values.currentTeamId}/feature_flags/${values.featureFlag.id}`,
                    payload
                )
                actions.setFeatureFlag(updatedFlag)
                featureFlagsLogic.findMounted()?.actions.updateFlag(updatedFlag)
            }
        },
        copyFlagSuccess: ({ featureFlagCopy }) => {
            if (featureFlagCopy?.success.length) {
                const operation = values.projectsWithCurrentFlag.find(
                    (p) => Number(p.team_id) === values.copyDestinationProject
                )
                    ? 'updated'
                    : 'copied'
                lemonToast.success(`Feature flag ${operation} successfully!`)
                eventUsageLogic.actions.reportFeatureFlagCopySuccess()
            } else {
                const errorMessage = JSON.stringify(featureFlagCopy?.failed) || featureFlagCopy
                lemonToast.error(`Error while saving feature flag: ${errorMessage}`)
                eventUsageLogic.actions.reportFeatureFlagCopyFailure(errorMessage)
            }

            actions.loadProjectsWithCurrentFlag()
            actions.setCopyDestinationProject(null)
        },
        createStaticCohortSuccess: ({ newCohort }) => {
            if (newCohort) {
                lemonToast.success('Static cohort created successfully', {
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(newCohort.id)),
                    },
                })
            }
        },
        createScheduledChangeSuccess: ({ scheduledChange }) => {
            if (scheduledChange) {
                lemonToast.success('Change scheduled successfully')
                actions.loadScheduledChanges()
                actions.setFeatureFlag({
                    ...values.featureFlag,
                    filters: NEW_FLAG.filters,
                    active: NEW_FLAG.active,
                })
                eventUsageLogic.actions.reportFeatureFlagScheduleSuccess()
            }
        },
        createScheduledChangeFailure: ({ error }) => {
            eventUsageLogic.actions.reportFeatureFlagScheduleFailure({ error })
        },
        deleteScheduledChangeSuccess: ({ scheduledChange }) => {
            if (scheduledChange) {
                lemonToast.success('Change has been deleted')
                actions.loadScheduledChanges()
            }
        },
    })),
    selectors({
        sentryErrorCount: [(s) => [s.sentryStats], (stats) => stats.total_count],
        sentryIntegrationEnabled: [(s) => [s.sentryStats], (stats) => !!stats.sentry_integration_enabled],
        props: [() => [(_, props) => props], (props) => props],
        multivariateEnabled: [(s) => [s.featureFlag], (featureFlag) => !!featureFlag?.filters.multivariate],
        roleBasedAccessEnabled: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS),
        ],
        variants: [(s) => [s.featureFlag], (featureFlag) => featureFlag?.filters.multivariate?.variants || []],
        nonEmptyVariants: [(s) => [s.variants], (variants) => variants.filter(({ key }) => !!key)],
        variantRolloutSum: [
            (s) => [s.variants],
            (variants) => variants.reduce((total: number, { rollout_percentage }) => total + rollout_percentage, 0),
        ],
        areVariantRolloutsValid: [
            (s) => [s.variants, s.variantRolloutSum],
            (variants, variantRolloutSum) =>
                variants.every(({ rollout_percentage }) => rollout_percentage >= 0 && rollout_percentage <= 100) &&
                variantRolloutSum === 100,
        ],
        aggregationTargetName: [
            (s) => [s.featureFlag, s.aggregationLabel],
            (featureFlag, aggregationLabel): string => {
                if (featureFlag && featureFlag.filters.aggregation_group_type_index != null) {
                    return aggregationLabel(featureFlag.filters.aggregation_group_type_index).plural
                }
                return 'users'
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.featureFlag, s.groupsTaxonomicTypes, s.enabledFeatures],
            (featureFlag, groupsTaxonomicTypes, enabledFeatures): TaxonomicFilterGroupType[] => {
                const baseGroupTypes = []
                const additionalGroupTypes = []
                const newFlagOperatorsEnabled = enabledFeatures[FEATURE_FLAGS.NEW_FEATURE_FLAG_OPERATORS]
                if (
                    featureFlag &&
                    featureFlag.filters.aggregation_group_type_index != null &&
                    groupsTaxonomicTypes.length > 0
                ) {
                    baseGroupTypes.push(groupsTaxonomicTypes[featureFlag.filters.aggregation_group_type_index])

                    if (newFlagOperatorsEnabled) {
                        additionalGroupTypes.push(
                            `${TaxonomicFilterGroupType.GroupNamesPrefix}_${featureFlag.filters.aggregation_group_type_index}` as unknown as TaxonomicFilterGroupType
                        )
                    }
                } else {
                    baseGroupTypes.push(TaxonomicFilterGroupType.PersonProperties)
                    baseGroupTypes.push(TaxonomicFilterGroupType.Cohorts)

                    if (newFlagOperatorsEnabled) {
                        additionalGroupTypes.push(TaxonomicFilterGroupType.Metadata)
                    }
                }

                return [...baseGroupTypes, ...additionalGroupTypes]
            },
        ],
        breadcrumbs: [
            (s) => [s.featureFlag],
            (featureFlag): Breadcrumb[] => [
                {
                    key: Scene.FeatureFlags,
                    name: 'Feature Flags',
                    path: urls.featureFlags(),
                },
                { key: [Scene.FeatureFlag, featureFlag.id || 'unknown'], name: featureFlag.key || 'Unnamed' },
            ],
        ],
        featureFlagTaxonomicOptions: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                if (featureFlag && featureFlag.filters.aggregation_group_type_index != null) {
                    return {}
                }

                const taxonomicOptions: TaxonomicFilterProps['optionsFromProp'] = {
                    [TaxonomicFilterGroupType.Metadata]: [
                        { name: 'distinct_id', propertyFilterType: PropertyFilterType.Person },
                    ],
                }
                return taxonomicOptions
            },
        ],
        propertySelectErrors: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return featureFlag?.filters?.groups?.map(
                    ({ properties, rollout_percentage }: FeatureFlagGroupType) => ({
                        properties: properties?.map((property: AnyPropertyFilter) => ({
                            value:
                                property.value === null ||
                                property.value === undefined ||
                                (Array.isArray(property.value) && property.value.length === 0)
                                    ? "Property filters can't be empty"
                                    : undefined,
                        })),
                        rollout_percentage:
                            rollout_percentage === undefined ? 'You need to set a rollout % value' : undefined,
                    })
                )
            },
        ],
        computeBlastRadiusPercentage: [
            (s) => [s.affectedUsers, s.totalUsers],
            (affectedUsers, totalUsers) => (rolloutPercentage, index) => {
                let effectiveRolloutPercentage = rolloutPercentage
                if (
                    rolloutPercentage === undefined ||
                    rolloutPercentage === null ||
                    (rolloutPercentage && rolloutPercentage > 100)
                ) {
                    effectiveRolloutPercentage = 100
                }

                if (
                    affectedUsers[index] === -1 ||
                    totalUsers === -1 ||
                    !totalUsers ||
                    affectedUsers[index] === undefined
                ) {
                    return effectiveRolloutPercentage
                }

                let effectiveTotalUsers = totalUsers
                if (effectiveTotalUsers === 0) {
                    effectiveTotalUsers = 1
                }

                return effectiveRolloutPercentage * (affectedUsers[index] / effectiveTotalUsers)
            },
        ],
        filteredDashboards: [
            (s) => [s.dashboards, s.featureFlag],
            (dashboards, featureFlag) => {
                if (!featureFlag) {
                    return dashboards
                }

                return dashboards.filter((dashboard: DashboardBasicType) => {
                    return featureFlag.analytics_dashboards?.includes(dashboard.id)
                })
            },
        ],
        recordingFilterForFlag: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                const flagKey = featureFlag?.key
                if (!flagKey) {
                    return {}
                }

                const defaultEntityFilterOnFlag: Partial<FilterType> = {
                    events: [
                        {
                            id: '$feature_flag_called',
                            name: '$feature_flag_called',
                            type: 'events',
                            properties: [
                                {
                                    key: '$feature/' + flagKey,
                                    type: PropertyFilterType.Event,
                                    value: ['false'],
                                    operator: PropertyOperator.IsNot,
                                },
                                {
                                    key: '$feature/' + flagKey,
                                    type: PropertyFilterType.Event,
                                    value: 'is_set',
                                    operator: PropertyOperator.IsSet,
                                },
                                {
                                    key: '$feature_flag',
                                    type: PropertyFilterType.Event,
                                    value: flagKey,
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                    ],
                }

                if (featureFlag.has_enriched_analytics) {
                    return {
                        events: [
                            {
                                id: '$feature_interaction',
                                type: 'events',
                                order: 0,
                                name: '$feature_interaction',
                                properties: [
                                    { key: 'feature_flag', value: [flagKey], operator: 'exact', type: 'event' },
                                ],
                            },
                        ],
                    }
                } else {
                    return defaultEntityFilterOnFlag
                }
            },
        ],
        hasEarlyAccessFeatures: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return (featureFlag?.features?.length || 0) > 0
            },
        ],
        canCreateEarlyAccessFeature: [
            (s) => [s.featureFlag, s.variants],
            (featureFlag, variants) => {
                return (
                    featureFlag &&
                    featureFlag.filters.aggregation_group_type_index == undefined &&
                    variants.length === 0
                )
            },
        ],
        hasSurveys: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return featureFlag?.surveys && featureFlag.surveys.length > 0
            },
        ],
    }),
    urlToAction(({ actions, props }) => ({
        [urls.featureFlag(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadFeatureFlag()
                } else {
                    actions.resetFeatureFlag()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        const foundFlag = featureFlagsLogic.findMounted()?.values.featureFlags.find((flag) => flag.id === props.id)
        if (foundFlag) {
            const formatPayloads = variantKeyToIndexFeatureFlagPayloads(foundFlag)
            actions.setFeatureFlag(formatPayloads)
            actions.loadRelatedInsights()
            actions.loadAllInsightsForFlag()
        } else if (props.id !== 'new' && props.id !== 'schedule') {
            actions.loadFeatureFlag()
        }
        actions.loadSentryStats()
    }),
])
