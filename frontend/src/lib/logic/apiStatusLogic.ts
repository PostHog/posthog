import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { userLogic } from 'scenes/userLogic'

import type { apiStatusLogicType } from './apiStatusLogicType'

export const apiStatusLogic = kea<apiStatusLogicType>([
    path(['lib', 'apiStatusLogic']),
    connect({
        actions: [router, ['locationChanged']],
    }),
    actions({
        onApiResponse: (response?: Response, error?: any, extra?: { method: string }) => ({ response, error, extra }),
        setInternetConnectionIssue: (issue: boolean) => ({ issue }),
        setTimeSensitiveAuthenticationRequired: (required: boolean) => ({ required }),
        setResourceAccessDenied: (resource: string) => ({ resource }),
        clearResourceAccessDenied: true,
    }),

    reducers({
        internetConnectionIssue: [
            false,
            {
                setInternetConnectionIssue: (_, { issue }) => issue,
            },
        ],

        timeSensitiveAuthenticationRequired: [
            false,
            {
                setTimeSensitiveAuthenticationRequired: (_, { required }) => required,
            },
        ],
        resourceAccessDenied: [
            null as string | null,
            {
                setResourceAccessDenied: (_, { resource }) => resource,
                clearResourceAccessDenied: () => null,
            },
        ],
    }),
    listeners(({ cache, actions, values }) => ({
        onApiResponse: async ({ response, error, extra }, breakpoint) => {
            const { method } = extra || {}
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

            try {
                if (response?.status === 403) {
                    const data = await response?.json()
                    if (data.detail === 'This action requires you to be recently authenticated.') {
                        actions.setTimeSensitiveAuthenticationRequired(true)
                    } else if (data.code === 'permission_denied') {
                        // TODO - only do if the RBAC feature flag is enabled
                        if (method === 'GET') {
                            actions.setResourceAccessDenied(data.resource || 'resource')
                        } else {
                            toast.error('You are not authorized to perform this action')
                        }
                    }
                }
            } catch (e) {
                // Pass
            }

            if (response?.status === 401) {
                if (!userLogic.findMounted()?.values.user) {
                    // We should only check and logout if we have a user
                    return
                }
                // api.ts calls this if we see a 401
                const now = Date.now()

                // We don't want to check too often (multiple api calls might fail at once)
                if (now - 10000 > (cache.lastUnauthorizedCheck ?? 0)) {
                    cache.lastUnauthorizedCheck = Date.now()

                    await api.get('api/users/@me/').catch((error: any) => {
                        if (error.status === 401) {
                            userLogic.findMounted()?.actions.logout()
                        }
                    })
                }
            }
        },
    })),
    listeners(({ actions }) => ({
        locationChanged: () => {
            actions.clearResourceAccessDenied()
        },
    })),
])
