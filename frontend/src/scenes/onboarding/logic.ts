import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { signupLogicType } from './logicType'

export const signupLogic = kea<signupLogicType>({
    loaders: () => ({
        account: [
            [],
            {
                createAccount: async (payload) => await api.create('api/signup/', payload),
            },
        ],
    }),

    listeners: {
        createAccountSuccess: ({ account }) => {
            if (account) {
                const dest = featureFlagLogic.values.featureFlags['onboarding-2822'] ? '/personalization' : '/ingestion'
                router.actions.push(dest)
            }
        },
    },
})
