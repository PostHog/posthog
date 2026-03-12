import { actions, kea, path, reducers } from 'kea'

import type { membersLogicType } from './membersLogicType'

// Toolbar shim — prevents the real membersLogic from auto-mounting and making API requests to the wrong host
export const membersLogic = kea<membersLogicType>([
    path(['toolbar', 'shims', 'membersLogic']),
    actions({
        ensureAllMembersLoaded: true,
    }),
    reducers({
        members: [[] as unknown[], {}],
    }),
])
