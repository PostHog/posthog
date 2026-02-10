import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'

import type { chooseAccountLogicType } from './chooseAccountLogicType'

export interface AccountChoice {
    user_id: string
    email: string
    name: string
}

export const chooseAccountLogic = kea<chooseAccountLogicType>([
    path(['scenes', 'authentication', 'chooseAccountLogic']),
    actions({
        selectAccount: (userId: string) => ({ userId }),
    }),
    reducers({
        selectedUserId: [
            null as string | null,
            {
                selectAccount: (_, { userId }) => userId,
            },
        ],
    }),
    loaders(() => ({
        choices: [
            [] as AccountChoice[],
            {
                loadChoices: async () => {
                    const response = await api.get('api/social/account-choices/')
                    return response.choices ?? []
                },
            },
        ],
        chooseResult: [
            null as { redirect_url: string } | null,
            {
                selectAccount: async ({ userId }) => {
                    const { searchParams } = router.values
                    const partialToken = searchParams.partial_token
                    const response = await api.create('api/social/choose-account/', {
                        user_id: userId,
                        partial_token: partialToken,
                    })
                    if (response.redirect_url) {
                        window.location.href = response.redirect_url
                    }
                    return response
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadChoices()
    }),
])
