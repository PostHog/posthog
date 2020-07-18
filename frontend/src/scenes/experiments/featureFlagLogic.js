import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'

export const featureFlagLogic = kea({
    key: (props) => props.id || 'new',

    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
    }),

    loaders: () => ({
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
            },
        ],
    }),
    reducers: () => ({
        featureFlags: {
            updateFeatureFlag: (state, featureFlag) => {
                if (!featureFlag) return null
                return [...state].map((flag) => (flag.id === featureFlag.id ? featureFlag : flag))
            },
            updateFeatureFlagSuccess: (state) => state,
            createFeatureFlagSuccess: (state, { featureFlags }) => {
                if (!featureFlags) return state
                return [featureFlags, ...state]
            },
        },
    }),
    listeners: ({ props }) => ({
        updateFeatureFlag: ({ featureFlag }) => featureFlag && props.closeDrawer(),
        updateFeatureFlagSuccess: ({ featureFlag }) => {
            featureFlag && toast('Feature flag saved.')
        },
        createFeatureFlagSuccess: ({ featureFlags }) => {
            if (!featureFlags) return null
            props.closeDrawer(), toast('Feature flag saved.')
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
