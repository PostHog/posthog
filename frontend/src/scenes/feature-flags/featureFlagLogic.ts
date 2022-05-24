import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import type { featureFlagLogicType } from './featureFlagLogicType'
import {
    AnyPropertyFilter,
    Breadcrumb,
    FeatureFlagType,
    MultivariateFlagOptions,
    MultivariateFlagVariant,
    PropertyFilter,
} from '~/types'
import api from 'lib/api'
import { router } from 'kea-router'
import { convertPropertyGroupToProperties, deleteWithUndo } from 'lib/utils'
import { urls } from 'scenes/urls'
import { teamLogic } from '../teamLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { lemonToast } from 'lib/components/lemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urlToAction } from 'kea-router'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

const NEW_FLAG: FeatureFlagType = {
    id: null,
    created_at: null,
    key: '',
    name: '',
    filters: { groups: [{ properties: [], rollout_percentage: null }], multivariate: null },
    deleted: false,
    active: true,
    created_by: null,
    is_simple_flag: false,
    rollout_percentage: null,
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

export interface FeatureFlagLogicProps {
    id: number | 'new'
}

export const featureFlagLogic = kea<featureFlagLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagLogic']),
    props({} as FeatureFlagLogicProps),
    key(({ id }) => id ?? 'new'),
    connect({
        values: [teamLogic, ['currentTeamId'], groupsModel, ['groupTypes', 'groupsTaxonomicTypes', 'aggregationLabel']],
    }),
    actions({
        setFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        addConditionSet: true,
        setAggregationGroupTypeIndex: (value: number | null) => ({ value }),
        removeConditionSet: (index: number) => ({ index }),
        duplicateConditionSet: (index: number) => ({ index }),
        updateConditionSet: (
            index: number,
            newRolloutPercentage?: number | null,
            newProperties?: AnyPropertyFilter[]
        ) => ({
            index,
            newRolloutPercentage,
            newProperties,
        }),
        deleteFeatureFlag: (featureFlag: Partial<FeatureFlagType>) => ({ featureFlag }),
        setMultivariateEnabled: (enabled: boolean) => ({ enabled }),
        setMultivariateOptions: (multivariateOptions: MultivariateFlagOptions | null) => ({ multivariateOptions }),
        addVariant: true,
        removeVariant: (index: number) => ({ index }),
        distributeVariantsEqually: true,
    }),
    forms(({ actions }) => ({
        featureFlag: {
            defaults: { ...NEW_FLAG } as FeatureFlagType,
            errors: ({ key, filters }) => ({
                key: !key
                    ? 'You need to set a key'
                    : !key.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
                    ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
                    : undefined,
                filters: {
                    multivariate: {
                        variants: filters?.multivariate?.variants?.map(
                            ({ key: variantKey }: MultivariateFlagVariant) => ({
                                key: !variantKey
                                    ? 'You need to set a key'
                                    : !variantKey.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
                                    ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
                                    : undefined,
                            })
                        ),
                    },
                },
            }),
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
                                    properties: convertPropertyGroupToProperties(group.properties) as PropertyFilter[],
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
                    const groups = [...state?.filters.groups, { properties: [], rollout_percentage: null }]
                    return { ...state, filters: { ...state.filters, groups } }
                },
                updateConditionSet: (state, { index, newRolloutPercentage, newProperties }) => {
                    if (!state) {
                        return state
                    }

                    const groups = [...state?.filters.groups]
                    if (newRolloutPercentage !== undefined) {
                        groups[index] = { ...groups[index], rollout_percentage: newRolloutPercentage }
                    }

                    if (newProperties !== undefined) {
                        groups[index] = { ...groups[index], properties: newProperties }
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

                    return {
                        ...state,
                        filters: {
                            ...state.filters,
                            aggregation_group_type_index: value,
                            // :TRICKY: We reset property filters after changing what you're aggregating by.
                            groups: [{ properties: [], rollout_percentage: null }],
                        },
                    }
                },
            },
        ],
    }),
    loaders(({ values, props }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                if (props.id && props.id !== 'new') {
                    return await api.get(`api/projects/${values.currentTeamId}/feature_flags/${props.id}`)
                }
                return NEW_FLAG
            },
            saveFeatureFlag: async (updatedFlag: Partial<FeatureFlagType>) => {
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                const { created_at, id, ...flag } = updatedFlag

                try {
                    if (!updatedFlag.id) {
                        return await api.create(`api/projects/${values.currentTeamId}/feature_flags`, flag)
                    } else {
                        return await api.update(
                            `api/projects/${values.currentTeamId}/feature_flags/${updatedFlag.id}`,
                            flag
                        )
                    }
                } catch (error: any) {
                    if (error.code === 'behavioral_cohort_found' || error.code === 'cohort_does_not_exist') {
                        eventUsageLogic.actions.reportFailedToCreateFeatureFlagWithCohort(error.code, error.detail)
                    }
                    throw error
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        saveFeatureFlagSuccess: ({ featureFlag }) => {
            lemonToast.success('Feature flag saved')
            featureFlagsLogic.findMounted()?.actions.updateFlag(featureFlag)
            router.actions.replace(urls.featureFlag(featureFlag.id))
        },
        deleteFeatureFlag: async ({ featureFlag }) => {
            deleteWithUndo({
                endpoint: `projects/${values.currentTeamId}/feature_flags`,
                object: { name: featureFlag.name, id: featureFlag.id },
                callback: () => {
                    featureFlag.id && featureFlagsLogic.findMounted()?.actions.deleteFlag(featureFlag.id)
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
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        multivariateEnabled: [(s) => [s.featureFlag], (featureFlag) => !!featureFlag?.filters.multivariate],
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
            (s) => [s.featureFlag, s.groupTypes, s.aggregationLabel],
            (featureFlag, groupTypes, aggregationLabel): string => {
                if (featureFlag && featureFlag.filters.aggregation_group_type_index != null && groupTypes.length > 0) {
                    return aggregationLabel(featureFlag.filters.aggregation_group_type_index).plural
                }
                return 'users'
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.featureFlag, s.groupsTaxonomicTypes],
            (featureFlag, groupsTaxonomicTypes): TaxonomicFilterGroupType[] => {
                if (
                    featureFlag &&
                    featureFlag.filters.aggregation_group_type_index != null &&
                    groupsTaxonomicTypes.length > 0
                ) {
                    return [groupsTaxonomicTypes[featureFlag.filters.aggregation_group_type_index]]
                }

                return [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]
            },
        ],
        breadcrumbs: [
            (s) => [s.featureFlag],
            (featureFlag): Breadcrumb[] => [
                {
                    name: 'Feature Flags',
                    path: urls.featureFlags(),
                },
                ...(featureFlag ? [{ name: featureFlag.key || 'Unnamed' }] : []),
            ],
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
            actions.setFeatureFlag(foundFlag)
        } else if (props.id !== 'new') {
            actions.loadFeatureFlag()
        }
    }),
])
