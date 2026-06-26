import { actions, events, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    usersLoginSessionsDestroy,
    usersLoginSessionsList,
    usersLoginSessionsRevokeOthersCreate,
} from '~/generated/core/api'
import type { UserAuthSessionApi } from '~/generated/core/api.schemas'

import type { loginSessionsLogicType } from './loginSessionsLogicType'

export const loginSessionsLogic = kea<loginSessionsLogicType>([
    path(['scenes', 'settings', 'user', 'loginSessionsLogic']),

    actions({
        revokeSession: (id: string) => ({ id }),
        revokeOtherSessions: true,
    }),

    loaders(({ values }) => ({
        loginSessions: [
            [] as UserAuthSessionApi[],
            {
                loadLoginSessions: async () => {
                    return await usersLoginSessionsList('@me')
                },
                revokeSession: async ({ id }) => {
                    await usersLoginSessionsDestroy('@me', id)
                    lemonToast.success('Logged out of that device')
                    return values.loginSessions.filter((session) => session.id !== id)
                },
                revokeOtherSessions: async () => {
                    const { revoked_count } = await usersLoginSessionsRevokeOthersCreate('@me')
                    lemonToast.success(
                        `Logged out of ${revoked_count} other ${revoked_count === 1 ? 'device' : 'devices'}`
                    )
                    return values.loginSessions.filter((session) => session.is_current)
                },
            },
        ],
    })),

    events(({ actions }) => ({
        afterMount: () => actions.loadLoginSessions(),
    })),
])
