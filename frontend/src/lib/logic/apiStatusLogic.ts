import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'

import type { apiStatusLogicType } from './apiStatusLogicType'

export const apiStatusLogic = kea<apiStatusLogicType>([
    path(['lib', 'apiStatusLogic']),
    actions({
        onApiResponse: (response?: Response, error?: any) => ({ response, error }),
        setInternetConnectionIssue: (issue: boolean) => ({ issue }),
    }),
    reducers({
        internetConnectionIssue: [
            false,
            {
                setInternetConnectionIssue: (_, { issue }) => issue,
            },
        ],
    }),
    listeners(({ cache, actions, values }) => ({
        onApiResponse: async ({ response, error }, breakpoint) => {
            if (error || !response?.status) {
                await breakpoint(50)
                // Likely CORS headers errors (i.e. request failing without reaching Django))
                if (error?.message === 'Failed to fetch') {
                    actions.setInternetConnectionIssue(true)
                }
            }

            if (response?.ok && values.internetConnectionIssue) {
                actions.setInternetConnectionIssue(false)
            }

            if (response?.status === 401) {
                // api.ts calls this if we see a 401
                const now = Date.now()

                // We don't want to check too often (multiple api calls might fail at once)
                if (now - 10000 > (cache.lastUnauthorizedCheck ?? 0)) {
                    cache.lastUnauthorizedCheck = Date.now()

                    await api.get('api/users/@me/').catch((error: any) => {
                        if (error.status === 401) {
                            window.location.href = '/logout'
                        }
                    })
                }
            }
        },
    })),
])
