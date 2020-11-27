import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { deleteWithUndo } from 'lib/utils'

export const featureFlagLogic = kea({
    key: (props) => props.id || 'new',

    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
    }),

    loaders: ({ actions }) => ({
        featureFlags: [
            [],
            {
                loadFeatureFlags: async () => {
                    return (await api.get('api/feature_flag/')).results
                },
                updateFeatureFlag: async (featureFlag) => {
                    try {
                        return await api.update('api/feature_flag/' + featureFlag.id, featureFlag)
                    } catch (err) {
                        if (err[0] === 'key-exists') {
                            toast.error('A feature flag with that key already exists')
                            return false
                        } else {
                            throw err
                        }
                    }
                },
                createFeatureFlag: async (featureFlag) => {
                    let create
                    try {
                        create = await api.create('api/feature_flag/', featureFlag)
                    } catch (err) {
                        if (err[0] === 'key-exists') {
                            toast.error('A feature flag with that key already exists')
                            return null
                        } else {
                            throw err
                        }
                    }
                    return create
                },
                deleteFeatureFlag: async (featureFlag) => {
                    try {
                        return deleteWithUndo({
                            endpoint: 'feature_flag',
                            object: { name: featureFlag.name, id: featureFlag.id },
                            callback: () => actions.loadFeatureFlags(),
                        })
                    } catch (err) {
                        toast.error('Unable to delete feature flag. Please try again later.')
                        return false
                    }
                },
            },
        ],
    }),
    reducers: () => ({
        featureFlags: {
            updateFeatureFlag: (state, featureFlag) => {
                if (!featureFlag) {
                    return null
                }
                return [...state].map((flag) => (flag.id === featureFlag.id ? featureFlag : flag))
            },
            updateFeatureFlagSuccess: (state) => state,
            createFeatureFlagSuccess: (state, { featureFlags }) => {
                if (!featureFlags) {
                    return state
                }
                return [featureFlags, ...state]
            },
            deleteFeatureFlag: (state, featureFlag) => {
                if (!featureFlag) {
                    return null
                }
                return [...state].filter((flag) => flag.id !== featureFlag.id)
            },
            deleteFeatureFlagSuccess: (state) => state,
        },
    }),
    listeners: ({ props }) => ({
        updateFeatureFlagSuccess: ({ featureFlags }) => {
            if (featureFlags) {
                toast('Feature flag saved.')
                props.closeDrawer()
            }
        },
        createFeatureFlagSuccess: ({ featureFlags }) => {
            if (!featureFlags) {
                return null
            }
            props.closeDrawer(), toast('Feature flag saved.')
        },
        deleteFeatureFlagSuccess: () => {
            props.closeDrawer()
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
