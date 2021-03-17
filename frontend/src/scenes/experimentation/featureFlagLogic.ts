import { kea } from 'kea'
import { featureFlagLogicType } from './featureFlagLogicType'
import { FeatureFlagType } from '~/types'
import api from 'lib/api'

const NEW_FLAG = {
    id: null,
    key: '',
    name: '',
    deleted: false,
    active: true,
    created_by: null,
    is_simple_flag: false,
    rollout_percentage: null,
}

export const featureFlagLogic = kea<featureFlagLogicType<FeatureFlagType>>({
    key: (props) => props.featureFlagId || 'new',
    loaders: ({ props }) => ({
        featureFlag: [
            null as FeatureFlagType | null,
            {
                loadFeatureFlag: async () => {
                    if (props.featureFlagId) {
                        return await api.get(`api/feature_flag/${props.featureFlagId}`)
                    }
                    return NEW_FLAG
                },
            },
        ],
    }),
    events: ({ actions }) => ({ afterMount: () => actions.loadFeatureFlag() }),
})
