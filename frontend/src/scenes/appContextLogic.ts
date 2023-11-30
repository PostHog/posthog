import * as Sentry from '@sentry/react'
import { afterMount, connect, kea, path } from 'kea'
import api from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'

import { UserType } from '~/types'

import type { appContextLogicType } from './appContextLogicType'
import { organizationLogic } from './organizationLogic'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

export const appContextLogic = kea<appContextLogicType>([
    path(['scenes', 'appContextLogic']),
    connect({
        actions: [
            userLogic,
            ['loadUserSuccess'],
            organizationLogic,
            ['loadCurrentOrganizationSuccess'],
            teamLogic,
            ['loadCurrentTeam', 'loadCurrentTeamSuccess'],
        ],
    }),
    afterMount(({ actions }) => {
        const appContext = getAppContext()
        const preloadedUser = appContext?.current_user

        if (appContext && preloadedUser) {
            void api.get('api/users/@me/').then((remoteUser: UserType) => {
                if (remoteUser.uuid !== preloadedUser.uuid) {
                    console.error(`Preloaded user ${preloadedUser.uuid} does not match remote user ${remoteUser.uuid}`)
                    Sentry.captureException(
                        new Error(`Preloaded user ${preloadedUser.uuid} does not match remote user ${remoteUser.uuid}`),
                        {
                            tags: {
                                posthog_app_context: JSON.stringify(getAppContext()),
                                remote_user: JSON.stringify(remoteUser),
                            },
                        }
                    )

                    // NOTE: This doesn't fix the issue but removes the confusion of seeing incorrect user info in the UI
                    actions.loadUserSuccess(remoteUser)
                    actions.loadCurrentOrganizationSuccess(remoteUser.organization)
                    actions.loadCurrentTeam()
                }
            })
        }
    }),
])
