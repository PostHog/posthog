import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, forms, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { sum, toParams } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { NEW_EARLY_ACCESS_FEATURE } from 'products/early_access_features/frontend/earlyAccessFeatureLogic'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { featureFlagsLogic, FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { projectLogic } from 'scenes/projectLogic'
import { Scene } from 'scenes/sceneTypes'
import { NEW_SURVEY, NewSurvey } from 'scenes/surveys/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { groupsModel } from '~/models/groupsModel'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import {
    AccessControlLevel,
    ActivityScope,
    AvailableFeature,
    Breadcrumb,
    CohortType,
    DashboardBasicType,
    EarlyAccessFeatureType,
    FeatureFlagGroupType,
    FeatureFlagRollbackConditions,
    FeatureFlagStatusResponse,
    FeatureFlagType,
    FilterLogicalOperator,
    FilterType,
    InsightModel,
    InsightType,
    JsonType,
    MultivariateFlagOptions,
    MultivariateFlagVariant,
    NewEarlyAccessFeatureType,
    OrganizationFeatureFlag,
    ProductKey,
    ProjectTreeRef,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
    RecordingUniversalFilters,
    RolloutConditionType,
    ScheduledChangeOperationType,
    ScheduledChangeType,
    Survey,
    SurveyQuestionType,
} from '~/types'

import { organizationLogic } from '../organizationLogic'
import { teamLogic } from '../teamLogic'
import type { featureFlagLogicType } from './featureFlagLogicType'
import { featureFlagPermissionsLogic } from './featureFlagPermissionsLogic'

export type ScheduleFlagPayload = Pick<FeatureFlagType, 'filters' | 'active'>

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

export const NEW_FLAG: FeatureFlagType = {
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
    user_access_level: AccessControlLevel.Editor,
    tags: [],
    is_remote_configuration: false,
    has_encrypted_payloads: false,
    status: 'ACTIVE',
    version: 0,
    last_modified_by: null,
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
        ? 'Please set a key'
        : key.length > 400
        ? 'Key must be 400 characters or less.'
        : !key.match?.(/^[a-zA-Z0-9_-]+$/)
        ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
        : undefined
}

function validatePayloadRequired(is_remote_configuration: boolean, payload?: JsonType): string | undefined {
    if (!is_remote_configuration) {
        return undefined
    }
    if (payload === undefined || payload === '') {
        return 'Payload is required for remote configuration flags.'
    }
    return undefined
}

export interface FeatureFlagLogicProps {
    id: number | 'new' | 'link'
}

// KLUDGE: Payloads are returned in a <variant-key>: <payload> mapping.
// This doesn't work for forms because variant-keys can be updated too which would invalidate the dictionary entry.
// If a multivariant flag is returned, the payload dictionary will be transformed to be <variant-key-index>: <payload>
export const variantKeyToIndexFeatureFlagPayloads = (flag: FeatureFlagType): FeatureFlagType => {
    if (!flag.filters.multivariate) {
        return flag
    }

    const newPayloads: Record<number, JsonType> = {}
    flag.filters.multivariate?.variants.forEach((variant, index) => {
        if (flag.filters.payloads?.[variant.key] !== undefined) {
            newPayloads[index] = flag.filters.payloads[variant.key]
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

export const indexToVariantKeyFeatureFlagPayloads = (flag: Partial<FeatureFlagType>): Partial<FeatureFlagType> => {
    if (flag.filters?.multivariate) {
        const newPayloads: Record<string, JsonType> = {}
        flag.filters.multivariate.variants.forEach(({ key }, index) => {
            if (flag.filters?.payloads?.[index] !== undefined) {
                newPayloads[key] = flag.filters.payloads[index]
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

export const getRecordingFilterForFlagVariant = (
    flagKey: string,
    variantKey: string | null,
    hasEnrichedAnalytics?: boolean
): Partial<RecordingUniversalFilters> => {
    return {
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        hasEnrichedAnalytics
                            ? {
                                  id: '$feature_interaction',
                                  type: 'events',
                                  order: 0,
                                  name: '$feature_interaction',
                                  properties: [
                                      {
                                          key: 'feature_flag',
                                          value: [flagKey],
                                          operator: PropertyOperator.Exact,
                                          type: PropertyFilterType.Event,
                                      },
                                  ],
                              }
                            : {
                                  type: PropertyFilterType.Event,
                                  key: `$feature/${flagKey}`,
                                  operator: PropertyOperator.Exact,
                                  value: [variantKey ? variantKey : 'true'],
                              },
                    ],
                },
            ],
        },
    }
}

// This helper function removes the created_at, id, and created_by fields from a flag
// and cleans the groups and super_groups by removing the sort_key field.
function cleanFlag(flag: Partial<FeatureFlagType>): Partial<FeatureFlagType> {
    const { created_at, id, created_by, last_modified_by, ...cleanedFlag } = flag
    return {
        ...cleanedFlag,
        filters: {
            ...cleanedFlag.filters,
            groups: cleanFilterGroups(cleanedFlag.filters?.groups) || [],
            super_groups: cleanFilterGroups(cleanedFlag.filters?.super_groups),
        },
    }
}

// Strip out sort_key from groups before saving. The sort_key is here for React to be able to
// render the release conditions in the correct order.
function cleanFilterGroups(groups?: FeatureFlagGroupType[]): FeatureFlagGroupType[] | undefined {
    if (groups === undefined || groups === null) {
        return undefined
    }
    return groups.map(({ sort_key, ...rest }: FeatureFlagGroupType) => rest)
}

export const featureFlagLogic = kea<featureFlagLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagLogic']),
    props({} as FeatureFlagLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect((props: FeatureFlagLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            projectLogic,
            ['currentProjectId'],
            groupsModel,
            ['aggregationLabel'],
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
            featureFlagsLogic,
            ['updateFlag', 'deleteFlag'],
            sidePanelStateLogic,
            ['closeSidePanel'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    actions({
        setFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        setFeatureFlagFilters: (filters: FeatureFlagType['filters'], errors: any) => ({ filters, errors }),
        setActiveTab: (tab: FeatureFlagsTab) => ({ tab }),
        setFeatureFlagMissing: true,
        addRollbackCondition: true,
        removeRollbackCondition: (index: number) => ({ index }),
        deleteFeatureFlag: (featureFlag: Partial<FeatureFlagType>) => ({ featureFlag }),
        restoreFeatureFlag: (featureFlag: Partial<FeatureFlagType>) => ({ featureFlag }),
        setRemoteConfigEnabled: (enabled: boolean) => ({ enabled }),
        resetEncryptedPayload: () => ({}),
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
        generateUsageDashboard: true,
        enrichUsageDashboard: true,
        setCopyDestinationProject: (id: number | null) => ({ id }),
        setScheduleDateMarker: (dateMarker: any) => ({ dateMarker }),
        setSchedulePayload: (
            filters: FeatureFlagType['filters'] | null,
            active: FeatureFlagType['active'] | null,
            errors?: any
        ) => ({ filters, active, errors }),
        setScheduledChangeOperation: (changeType: ScheduledChangeOperationType) => ({ changeType }),
        setAccessDeniedToFeatureFlag: true,
    }),
    forms(({ actions, values }) => ({
        featureFlag: {
            defaults: {
                ...NEW_FLAG,
                ensure_experience_continuity: values.currentTeam?.flags_persistence_default || false,
            },
            errors: ({ key, filters, is_remote_configuration }) => {
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
                        payloads: {
                            true: validatePayloadRequired(is_remote_configuration, filters?.payloads?.['true']),
                        } as any,
                        // Forced any cast necessary to prevent Kea's typechecking from raising "Type instantiation
                        // is excessively deep and possibly infinite" error
                    },
                }
            },
            submit: (featureFlag) => {
                if (featureFlag.id) {
                    actions.saveFeatureFlag(featureFlag)
                } else {
                    actions.saveFeatureFlag({ ...featureFlag, _create_in_folder: 'Unfiled/Feature Flags' })
                }
            },
        },
    })),
    reducers({
        originalFeatureFlag: [
            null as FeatureFlagType | null,
            {
                loadFeatureFlagSuccess: (_, { featureFlag }) => {
                    // Transform the original flag when it's first loaded
                    // Apply the same transformations we'd use when sending it back
                    return featureFlag
                        ? (indexToVariantKeyFeatureFlagPayloads(cleanFlag(featureFlag)) as FeatureFlagType)
                        : null
                },
            },
        ],
        featureFlag: [
            { ...NEW_FLAG } as FeatureFlagType,
            {
                setFeatureFlag: (_, { featureFlag }) => {
                    return featureFlag
                },
                setFeatureFlagFilters: (state, { filters }) => {
                    return { ...state, filters }
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
                setMultivariateOptions: (state, { multivariateOptions }) => {
                    if (!state) {
                        return state
                    }
                    const variantsSet = new Set(multivariateOptions?.variants.map((variant) => variant.key))
                    const groups = state.filters.groups.map((group) =>
                        !group.variant || variantsSet.has(group.variant) ? group : { ...group, variant: null }
                    )
                    const oldPayloads = state.filters.payloads ?? {}
                    const payloads: Record<string, JsonType> = {}
                    for (const variantKey of Object.keys(oldPayloads)) {
                        if (variantsSet.has(variantKey)) {
                            payloads[variantKey] = oldPayloads[variantKey]
                        }
                    }
                    return {
                        ...state,
                        filters: { ...state.filters, groups, payloads, multivariate: multivariateOptions },
                    }
                },
                setRemoteConfigEnabled: (state, { enabled }) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        is_remote_configuration: enabled,
                    }
                },
                resetEncryptedPayload: (state) => {
                    if (!state) {
                        return state
                    }

                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            payloads: { true: '' },
                        },
                        has_encrypted_payloads: false,
                    }
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
                                ...state.filters.multivariate,
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

                    const currentPayloads = { ...state.filters.payloads }
                    const newPayloads: Record<number, any> = {}

                    // TRICKY: In addition to modifying the variant array, we also need to shift the payload indices
                    // because the variant array is being modified and we need to make sure that the payloads object
                    // stays in sync with the variant array.
                    Object.keys(currentPayloads).forEach((key) => {
                        const payloadIndex = parseInt(key)
                        if (payloadIndex > index) {
                            newPayloads[payloadIndex - 1] = currentPayloads[payloadIndex]
                        } else if (payloadIndex < index) {
                            newPayloads[payloadIndex] = currentPayloads[payloadIndex]
                        }
                    })

                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            multivariate: {
                                ...state.filters.multivariate,
                                variants,
                            },
                            payloads: newPayloads,
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
            },
        ],
        accessDeniedToFeatureFlag: [false, { setAccessDeniedToFeatureFlag: () => true }],
        propertySelectErrors: [
            null as any,
            {
                setFeatureFlagFilters: (_, { errors }) => {
                    return errors
                },
            },
        ],
        activeTab: [
            FeatureFlagsTab.OVERVIEW as FeatureFlagsTab,
            {
                setActiveTab: (_, { tab }) => tab,
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
        schedulePayload: [
            {
                filters: { ...NEW_FLAG.filters },
                active: NEW_FLAG.active,
            } as ScheduleFlagPayload,
            {
                setSchedulePayload: (state, { filters, active }) => {
                    return {
                        filters: filters === null ? state.filters : filters,
                        active: active === null ? state.active : active,
                    }
                },
            },
        ],
        schedulePayloadErrors: [
            null as any,
            {
                setSchedulePayload: (state, { errors }) => {
                    return errors === null || errors === undefined ? state : errors
                },
            },
        ],
        scheduledChangeOperation: [
            ScheduledChangeOperationType.AddReleaseCondition as ScheduledChangeOperationType,
            {
                setScheduledChangeOperation: (_, { changeType }) => changeType,
            },
        ],
    }),
    loaders(({ values, props, actions }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                const sourceId = router.values.searchParams.sourceId
                if (props.id === 'new' && sourceId) {
                    // Used when "duplicating a feature flag". This populates the form with the source flag's data.
                    const sourceFlag = await api.featureFlags.get(sourceId)
                    // But first, remove fields that we don't want to duplicate
                    const {
                        id,
                        created_at,
                        key,
                        deleted,
                        active,
                        created_by,
                        is_simple_flag,
                        experiment_set,
                        features,
                        surveys,
                        performed_rollback,
                        can_edit,
                        user_access_level,
                        status,
                        last_modified_by,
                        ...flagToKeep
                    } = sourceFlag

                    // Remove sourceId from URL
                    router.actions.replace(router.values.location.pathname)

                    return {
                        ...NEW_FLAG,
                        ...flagToKeep,
                        key: '',
                    } as FeatureFlagType
                }

                if (props.id && props.id !== 'new' && props.id !== 'link') {
                    try {
                        const retrievedFlag: FeatureFlagType = await api.featureFlags.get(props.id)
                        return variantKeyToIndexFeatureFlagPayloads(retrievedFlag)
                    } catch (e: any) {
                        if (e.status === 403 && e.code === 'permission_denied') {
                            actions.setAccessDeniedToFeatureFlag()
                        } else {
                            actions.setFeatureFlagMissing()
                        }
                        throw e
                    }
                }
                return {
                    ...NEW_FLAG,
                    ensure_experience_continuity: values.currentTeam?.flags_persistence_default ?? false,
                }
            },
            saveFeatureFlag: async (updatedFlag: Partial<FeatureFlagType>) => {
                // Destructure all fields we want to exclude or handle specially
                const flag = cleanFlag(updatedFlag)
                const preparedFlag = indexToVariantKeyFeatureFlagPayloads(flag)

                try {
                    let savedFlag: FeatureFlagType
                    if (!updatedFlag.id) {
                        // Creating a new flag
                        savedFlag = await api.create(
                            `api/projects/${values.currentProjectId}/feature_flags`,
                            preparedFlag
                        )
                        if (values.roleBasedAccessEnabled && savedFlag.id) {
                            featureFlagPermissionsLogic({ flagId: null })?.actions.addAssociatedRoles(savedFlag.id)
                        }
                        actions.addProductIntent({
                            product_type: ProductKey.FEATURE_FLAGS,
                            intent_context: ProductIntentContext.FEATURE_FLAG_CREATED,
                        })
                    } else {
                        // Updating an existing flag - include version in preparedFlag
                        const cachedFlag = featureFlagsLogic
                            .findMounted()
                            ?.values.featureFlags.results.find((flag) => flag.id === props.id)

                        // If we've got a cached flag and the filters have changed, we've updated the release conditions
                        if (
                            cachedFlag &&
                            JSON.stringify(cachedFlag?.filters) !== JSON.stringify(values.featureFlag.filters)
                        ) {
                            activationLogic
                                .findMounted()
                                ?.actions.markTaskAsCompleted(ActivationTask.UpdateFeatureFlagReleaseConditions)
                        }

                        savedFlag = await api.update(
                            `api/projects/${values.currentProjectId}/feature_flags/${updatedFlag.id}`,
                            {
                                ...preparedFlag,
                                original_flag: values.originalFeatureFlag,
                            }
                        )
                    }
                    savedFlag.id && refreshTreeItem('feature_flag', String(savedFlag.id))
                    return variantKeyToIndexFeatureFlagPayloads(savedFlag)
                } catch (error: any) {
                    if (error.code === 'behavioral_cohort_found' || error.code === 'cohort_does_not_exist') {
                        eventUsageLogic.actions.reportFailedToCreateFeatureFlagWithCohort(error.code, error.detail)
                    }
                    throw error
                }
            },
            saveSidebarExperimentFeatureFlag: async (updatedFlag: Partial<FeatureFlagType>) => {
                const flag = cleanFlag(updatedFlag)

                const preparedFlag = indexToVariantKeyFeatureFlagPayloads(flag)

                try {
                    let savedFlag: FeatureFlagType
                    if (!updatedFlag.id) {
                        // Creating a new flag
                        savedFlag = await api.create(
                            `api/projects/${values.currentProjectId}/feature_flags`,
                            preparedFlag
                        )
                        if (values.roleBasedAccessEnabled && savedFlag.id) {
                            featureFlagPermissionsLogic({ flagId: null })?.actions.addAssociatedRoles(savedFlag.id)
                        }
                    } else {
                        savedFlag = await api.update(
                            `api/projects/${values.currentProjectId}/feature_flags/${updatedFlag.id}`,
                            {
                                ...preparedFlag,
                                original_flag: values.originalFeatureFlag,
                            }
                        )
                    }
                    savedFlag.id && refreshTreeItem('feature_flag', String(savedFlag.id))

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
            [] as QueryBasedInsightModel[],
            {
                loadRelatedInsights: async () => {
                    if (props.id && props.id !== 'new' && values.featureFlag.key) {
                        const response = await api.get<PaginatedResponse<InsightModel>>(
                            `api/environments/${values.currentProjectId}/insights/?feature_flag=${values.featureFlag.key}&order=-created_at`
                        )
                        return response.results.map((legacyInsight) => getQueryBasedInsightModel(legacyInsight))
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
                    if (props.id && props.id !== 'new' && props.id !== 'link') {
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

                const organizationFeatureFlags = await api.organizationFeatureFlags.get(orgId, flagKey)
                const teamIdsInCurrentProject =
                    values.currentOrganization?.teams
                        .filter((t) => t.project_id === values.currentProjectId)
                        .map((t) => t.id) || []

                // Put current project first. We need teamIdsInCurrentProject here, because as of Feb 2025,
                // FeatureFlag only has `team_id`, but not `project_id`
                return organizationFeatureFlags.sort((a, b) => {
                    if (teamIdsInCurrentProject.includes(a.team_id)) {
                        return -1
                    }
                    if (teamIdsInCurrentProject.includes(b.team_id)) {
                        return 1
                    }
                    return 0
                })
            },
        },
        featureFlagCopy: {
            copyFlag: async () => {
                const orgId = values.currentOrganization?.id
                const featureFlagKey = values.featureFlag.key
                const { copyDestinationProject, currentProjectId } = values

                if (currentProjectId && copyDestinationProject) {
                    return await api.organizationFeatureFlags.copy(orgId, {
                        feature_flag_key: featureFlagKey,
                        from_project: currentProjectId,
                        target_project_ids: [copyDestinationProject],
                    })
                }
            },
        },
        scheduledChanges: {
            __default: [] as ScheduledChangeType[],
            loadScheduledChanges: async () => {
                const { currentProjectId } = values
                if (currentProjectId) {
                    const response = await api.featureFlags.getScheduledChanges(currentProjectId, values.featureFlag.id)
                    return response.results || []
                }
            },
        },
        scheduledChange: {
            __default: {} as ScheduledChangeType,
            createScheduledChange: async () => {
                const { scheduledChangeOperation, scheduleDateMarker, currentProjectId, schedulePayload } = values

                const fields: Record<ScheduledChangeOperationType, keyof ScheduleFlagPayload> = {
                    [ScheduledChangeOperationType.UpdateStatus]: 'active',
                    [ScheduledChangeOperationType.AddReleaseCondition]: 'filters',
                }

                if (currentProjectId && scheduledChangeOperation) {
                    const data = {
                        record_id: values.featureFlag.id,
                        model_name: 'FeatureFlag',
                        payload: {
                            operation: scheduledChangeOperation,
                            value: schedulePayload[fields[scheduledChangeOperation]],
                        },
                        scheduled_at: scheduleDateMarker.toISOString(),
                    }

                    return await api.featureFlags.createScheduledChange(currentProjectId, data)
                }
            },
            deleteScheduledChange: async (scheduledChangeId) => {
                const { currentProjectId } = values
                if (currentProjectId) {
                    return await api.featureFlags.deleteScheduledChange(currentProjectId, scheduledChangeId)
                }
            },
        },
        flagStatus: [
            null as FeatureFlagStatusResponse | null,
            {
                loadFeatureFlagStatus: () => {
                    const { currentProjectId } = values
                    if (currentProjectId && props.id && props.id !== 'new' && props.id !== 'link') {
                        return api.featureFlags.getStatus(currentProjectId, props.id)
                    }
                    return null
                },
            },
        ],
        experiment: {
            loadExperiment: async () => {
                if (values.featureFlag.experiment_set) {
                    return await api.experiments.get(values.featureFlag.experiment_set[0])
                }
                return null
            },
        },
    })),
    listeners(({ actions, values, props }) => ({
        submitNewDashboardSuccessWithResult: async ({ result }) => {
            await api.update(`api/projects/${values.currentProjectId}/feature_flags/${values.featureFlag.id}`, {
                analytics_dashboards: [result.id],
            })
        },
        generateUsageDashboard: async () => {
            if (props.id) {
                await api.create(`api/projects/${values.currentProjectId}/feature_flags/${props.id}/dashboard`)
                actions.loadFeatureFlag()
            }
        },
        enrichUsageDashboard: async (_, breakpoint) => {
            if (props.id) {
                await breakpoint(1000) // in ms
                await api.create(
                    `api/projects/${values.currentProjectId}/feature_flags/${props.id}/enrich_usage_dashboard`
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
            actions.updateFlag(featureFlag)
            featureFlag.id && router.actions.replace(urls.featureFlag(featureFlag.id))
            actions.editFeatureFlag(false)
            activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.CreateFeatureFlag)
        },
        saveSidebarExperimentFeatureFlagSuccess: ({ featureFlag }) => {
            lemonToast.success('Release conditions updated')
            actions.updateFlag(featureFlag)
            actions.editFeatureFlag(false)
            actions.closeSidePanel()

            const currentPath = router.values.currentLocation.pathname
            const experimentId = currentPath.split('/').pop()

            if (experimentId) {
                eventUsageLogic.actions.reportExperimentReleaseConditionsUpdated(parseInt(experimentId))
                experimentLogic({ experimentId: parseInt(experimentId) }).actions.loadExperiment()
            }
        },
        deleteFeatureFlag: async ({ featureFlag }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/feature_flags`,
                object: { name: featureFlag.key, id: featureFlag.id },
                callback: (undo) => {
                    featureFlag.id && actions.deleteFlag(featureFlag.id)
                    if (undo) {
                        refreshTreeItem('feature_flag', String(featureFlag.id))
                    } else {
                        deleteFromTree('feature_flag', String(featureFlag.id))
                    }
                    // Load latest change so a backwards navigation shows the flag as deleted
                    actions.loadFeatureFlag()
                    router.actions.push(urls.featureFlags())
                },
            })
        },
        restoreFeatureFlag: async ({ featureFlag }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/feature_flags`,
                object: { name: featureFlag.key, id: featureFlag.id },
                undo: true,
                callback: (undo) => {
                    if (undo) {
                        deleteFromTree('feature_flag', String(featureFlag.id))
                    } else {
                        refreshTreeItem('feature_flag', String(featureFlag.id))
                    }
                    actions.loadFeatureFlag()
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
            actions.loadExperiment()
        },
        loadInsightAtIndex: async ({ index, filters }) => {
            if (filters) {
                const response = await api.get(
                    `api/environments/${values.currentProjectId}/insights/trend/?${toParams(
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
                actions.setSchedulePayload(NEW_FLAG.filters, NEW_FLAG.active, {})
                actions.loadScheduledChanges()
                eventUsageLogic.actions.reportFeatureFlagScheduleSuccess()
            }
        },
        setScheduledChangeOperation: () => {
            // reset filters when operation changes
            actions.setSchedulePayload(NEW_FLAG.filters, NEW_FLAG.active, {})
        },
        setActiveTab: ({ tab }) => {
            // reset filters when opening schedule tab, and load scheduled changes
            if (tab === FeatureFlagsTab.SCHEDULE) {
                actions.setSchedulePayload(NEW_FLAG.filters, NEW_FLAG.active, {})
                actions.loadScheduledChanges()
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
        setRemoteConfigEnabled: ({ enabled }) => {
            if (enabled) {
                actions.setFeatureFlagFilters(
                    {
                        ...values.featureFlag.filters,
                        groups: [
                            {
                                variant: null,
                                properties: [],
                                rollout_percentage: 100,
                            },
                        ],
                    },
                    {}
                )
            }
        },
        editFeatureFlag: async ({ editing }) => {
            if (editing) {
                actions.loadFeatureFlag()
            }
        },
    })),
    selectors({
        sentryErrorCount: [(s) => [s.sentryStats], (stats) => stats.total_count],
        sentryIntegrationEnabled: [(s) => [s.sentryStats], (stats) => !!stats.sentry_integration_enabled],
        props: [() => [(_, props) => props], (props) => props],
        multivariateEnabled: [(s) => [s.featureFlag], (featureFlag) => !!featureFlag?.filters.multivariate],
        flagType: [
            (s) => [s.featureFlag],
            (featureFlag) =>
                featureFlag?.is_remote_configuration
                    ? 'remote_config'
                    : featureFlag?.filters.multivariate
                    ? 'multivariate'
                    : 'boolean',
        ],
        flagTypeString: [
            (s) => [s.featureFlag],
            (featureFlag) =>
                featureFlag?.is_remote_configuration
                    ? 'Remote configuration (single payload)'
                    : featureFlag?.filters.multivariate
                    ? 'Multiple variants with rollout percentages (A/B/n test)'
                    : 'Release toggle (boolean)',
        ],
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
        projectTreeRef: [
            () => [(_, props: FeatureFlagLogicProps) => props.id],
            (id): ProjectTreeRef => ({ type: 'feature_flag', ref: id === 'link' || id === 'new' ? null : String(id) }),
        ],

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.featureFlag],
            (featureFlag): SidePanelSceneContext | null => {
                return featureFlag?.id
                    ? {
                          activity_scope: ActivityScope.FEATURE_FLAG,
                          activity_item_id: `${featureFlag.id}`,
                          access_control_resource: 'feature_flag',
                          access_control_resource_id: `${featureFlag.id}`,
                      }
                    : null
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
            (featureFlag): Partial<RecordingUniversalFilters> => {
                const flagKey = featureFlag?.key
                if (!flagKey) {
                    return {}
                }

                return getRecordingFilterForFlagVariant(flagKey, null, featureFlag.has_enriched_analytics)
            },
        ],
        hasEarlyAccessFeatures: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return (featureFlag?.features?.length || 0) > 0
            },
        ],
        earlyAccessFeaturesList: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return featureFlag?.features || []
            },
        ],
        featureFlagKey: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return featureFlag.key
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
        hasEncryptedPayloadBeenSaved: [
            (s) => [s.featureFlag, s.props],
            (featureFlag, props) => {
                if (!featureFlag.has_encrypted_payloads) {
                    return false
                }
                const savedFlag = featureFlagsLogic
                    .findMounted()
                    ?.values.featureFlags.results.find((flag) => flag.id === props.id)
                return savedFlag?.has_encrypted_payloads
            },
        ],
        hasExperiment: [
            (s) => [s.featureFlag],
            (featureFlag) => {
                return featureFlag?.experiment_set && featureFlag.experiment_set.length > 0
            },
        ],
        isDraftExperiment: [
            (s) => [s.experiment],
            (experiment) => {
                // Treat as launched experiment if not yet loaded.
                if (!experiment) {
                    return false
                }
                return !experiment?.start_date
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
        if (props.id === 'new' && router.values.searchParams.sourceId) {
            actions.loadFeatureFlag()
            return
        }

        const foundFlag = featureFlagsLogic
            .findMounted()
            ?.values.featureFlags.results.find((flag) => flag.id === props.id)
        if (foundFlag) {
            const formatPayloadsWithFlag = variantKeyToIndexFeatureFlagPayloads(foundFlag)
            actions.setFeatureFlag(formatPayloadsWithFlag)
            actions.loadRelatedInsights()
            actions.loadAllInsightsForFlag()
            actions.loadFeatureFlagStatus()
        } else if (props.id !== 'new') {
            actions.loadFeatureFlag()
            actions.loadFeatureFlagStatus()
        }
    }),
])
