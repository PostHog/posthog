import { kea } from 'kea'
import React from 'react'
import { featureFlagLogicType } from './featureFlagLogicType'
import { AnyPropertyFilter, FeatureFlagType, MultivariateFlagOptions, MultivariateFlagVariant } from '~/types'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { router } from 'kea-router'
import { deleteWithUndo } from 'lib/utils'
import { urls } from 'scenes/sceneLogic'
const NEW_FLAG = {
    id: null,
    key: '',
    name: '',
    filters: { groups: [{ properties: [], rollout_percentage: null }] },
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

export const featureFlagLogic = kea<featureFlagLogicType>({
    actions: {
        setFeatureFlagId: (id: number | 'new') => ({ id }),
        addMatchGroup: true,
        removeMatchGroup: (index: number) => ({ index }),
        updateMatchGroup: (
            index: number,
            newRolloutPercentage?: number | null,
            newProperties?: AnyPropertyFilter[]
        ) => ({
            index,
            newRolloutPercentage,
            newProperties,
        }),
        deleteFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        setMultivariateEnabled: (enabled: boolean) => ({ enabled }),
        setMultivariateOptions: (multivariateOptions: MultivariateFlagOptions | null) => ({ multivariateOptions }),
        addVariant: true,
        updateVariant: (index: number, newProperties: Partial<MultivariateFlagVariant>) => ({ index, newProperties }),
        removeVariant: (index: number) => ({ index }),
        distributeVariantsEqually: true,
    },
    reducers: {
        featureFlagId: [
            null as null | number | 'new',
            {
                setFeatureFlagId: (_, { id }) => id,
            },
        ],
        featureFlag: [
            null as FeatureFlagType | null,
            {
                addMatchGroup: (state) => {
                    if (!state) {
                        return state
                    }
                    const groups = [...state?.filters.groups, { properties: [], rollout_percentage: null }]
                    return { ...state, filters: { ...state.filters, groups } }
                },
                updateMatchGroup: (state, { index, newRolloutPercentage, newProperties }) => {
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
                removeMatchGroup: (state, { index }) => {
                    if (!state) {
                        return state
                    }
                    const groups = [...state.filters.groups]
                    groups.splice(index, 1)
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
                updateVariant: (state, { index, newProperties }) => {
                    if (!state) {
                        return state
                    }
                    const variants = [...(state.filters.multivariate?.variants || [])]
                    if (!variants[index]) {
                        return state
                    }
                    variants[index] = {
                        ...variants[index],
                        ...newProperties,
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
            },
        ],
    },
    loaders: ({ values }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                if (values.featureFlagId && values.featureFlagId !== 'new') {
                    return await api.get(`api/feature_flag/${values.featureFlagId}`)
                }
                return NEW_FLAG
            },
            saveFeatureFlag: async (updatedFlag: Partial<FeatureFlagType>) => {
                if (!updatedFlag.id) {
                    return await api.create('api/feature_flag', {
                        ...updatedFlag,
                        id: undefined,
                    })
                } else {
                    return await api.update(`api/feature_flag/${updatedFlag.id}`, {
                        ...updatedFlag,
                        id: undefined,
                    })
                }
            },
        },
    }),
    listeners: ({ actions }) => ({
        saveFeatureFlagSuccess: () => {
            toast.success(
                <div>
                    <h1>Your feature flag has been saved!</h1>
                    <p>Click here to back to the feature flag list.</p>
                </div>,
                {
                    onClick: () => {
                        router.actions.push(urls.featureFlags())
                    },
                    closeOnClick: true,
                }
            )
        },
        deleteFeatureFlag: async ({ featureFlag }) => {
            deleteWithUndo({
                endpoint: 'feature_flag',
                object: { name: featureFlag.name, id: featureFlag.id },
                callback: () => {
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
    }),
    selectors: {
        multivariateEnabled: [(s) => [s.featureFlag], (featureFlag) => !!featureFlag?.filters.multivariate],
        variants: [(s) => [s.featureFlag], (featureFlag) => featureFlag?.filters?.multivariate?.variants || []],
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
    },
    urlToAction: ({ actions }) => ({
        '/feature_flags/*': ({ _: id }) => {
            if (id) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                actions.setFeatureFlagId(parsedId)
            }
            actions.loadFeatureFlag()
        },
    }),
})
