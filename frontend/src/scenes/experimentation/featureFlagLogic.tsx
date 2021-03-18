import { kea } from 'kea'
import React from 'react'
import { featureFlagLogicType } from './featureFlagLogicType'
import { FeatureFlagType, PropertyFilter } from '~/types'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { router } from 'kea-router'
import { deleteWithUndo } from 'lib/utils'

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

export const featureFlagLogic = kea<featureFlagLogicType<FeatureFlagType>>({
    actions: {
        setFeatureFlagId: (id) => ({ id }),
        addMatchGroup: true,
        removeMatchGroup: (index: number) => ({ index }),
        updateMatchGroup: (index: number, newRolloutPercentage?: number | null, newProperties?: PropertyFilter[]) => ({
            index,
            newRolloutPercentage,
            newProperties,
        }),
        deleteFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
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
            },
        ],
    },
    loaders: ({ values }) => ({
        featureFlag: [
            null,
            {
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
        ],
    }),
    listeners: {
        saveFeatureFlagSuccess: () => {
            toast.success(
                <div>
                    <h1>Your feature flag has been saved!</h1>
                    <p>Click here to back to the feature flag list.</p>
                </div>,
                {
                    onClick: () => {
                        router.actions.push('/feature_flags')
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
                    router.actions.push('/feature_flags')
                },
            })
        },
    },
    urlToAction: ({ actions }) => ({
        '/feature_flags/*': ({ _: id }: { _: number | 'new' }) => {
            actions.setFeatureFlagId(id)
            actions.loadFeatureFlag()
        },
    }),
})
