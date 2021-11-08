import { kea } from 'kea'
import api from 'lib/api'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { FeatureFlagType } from '~/types'
import { teamLogic } from '../teamLogic'

export const featureFlagsLogic = kea<featureFlagsLogicType>({
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        updateFlag: (flag: FeatureFlagType) => ({ flag }),
    },
    loaders: ({ values }) => ({
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const response = await api.get(`api/projects/${values.currentTeamId}/feature_flags/`)
                return response.results as FeatureFlagType[]
            },
            updateFeatureFlag: async ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
                const response = await api.update(`api/projects/${values.currentTeamId}/feature_flags/${id}`, payload)
                return [...values.featureFlags].map((flag) => (flag.id === response.id ? response : flag))
            },
        },
    }),
    reducers: {
        featureFlags: {
            updateFlag: (state, { flag }) => {
                if (state.find(({ id }) => id === flag.id)) {
                    return state.map((stateFlag) => (stateFlag.id === flag.id ? flag : stateFlag))
                } else {
                    return [flag, ...state]
                }
            },
        },
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
