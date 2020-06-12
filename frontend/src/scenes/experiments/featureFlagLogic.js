import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'

export const featureFlagLogic = kea({
    key: props => props.id || 'new',

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
                updateFeatureFlag: async featureFlag => {
                    return await api.update('api/feature_flag/' + featureFlag.id, featureFlag)
                },
                createFeatureFlag: async featureFlag => {
                    return await api.create('api/feature_flag/', featureFlag)
                },
            },
        ],
    }),
    reducers: () => ({
        featureFlags: {
            updateFeatureFlag: (state, featureFlag) => {
                return [...state].map(flag => (flag.id === featureFlag.id ? featureFlag : flag))
            },
            updateFeatureFlagSuccess: state => state,
            createFeatureFlagSuccess: (state, { featureFlags }) => {
                return [featureFlags, ...state]
            },
        },
    }),
    listeners: ({ props }) => ({
        updateFeatureFlag: () => props.closeDrawer(),
        updateFeatureFlagSuccess: () => {
            toast('Feature flag saved.')
        },
        createFeatureFlagSuccess: () => {
            props.closeDrawer(), toast('Feature flag saved.')
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
