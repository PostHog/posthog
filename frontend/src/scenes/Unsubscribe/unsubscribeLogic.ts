import { actions, afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'

import type { unsubscribeLogicType } from './unsubscribeLogicType'

export const unsubscribeLogic = kea<unsubscribeLogicType>([
    path(['scenes', 'Unsubscribe', 'unsubscribeLogic']),
    actions({
        attemptUnsubscribe: (token: string) => ({ token }),
    }),

    loaders(() => ({
        unsubscription: {
            __default: false as boolean,
            attemptUnsubscribe: async ({ token }) => {
                const res = await api.get(`api/unsubscribe?token=${token}`)
                return res.success
            },
        },
    })),
    afterMount(({ actions }) => {
        const { token } = router.values.searchParams
        actions.attemptUnsubscribe(token)
    }),
])
