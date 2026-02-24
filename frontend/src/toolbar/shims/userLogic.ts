import { actions, kea, path, reducers } from 'kea'

import type { userLogicType } from './userLogicType'

// Toolbar shim — prevents the real userLogic from auto-mounting and making API requests to the wrong host
export const userLogic = kea<userLogicType>([
    path(['toolbar', 'shims', 'userLogic']),
    actions({
        updateUser: (payload: unknown) => ({ payload }),
        loadUserSuccess: (user: unknown) => ({ user }),
    }),
    reducers({
        user: [null as Record<string, unknown> | null, {}],
        themeMode: ['system' as string, {}],
    }),
])
