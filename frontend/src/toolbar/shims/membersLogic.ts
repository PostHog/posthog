import { actions, kea, path, reducers } from 'kea'

// Toolbar shim — prevents the real membersLogic from auto-mounting and making API requests to the wrong host
export const membersLogic = kea([
    path(['toolbar', 'shims', 'membersLogic']),
    actions({
        ensureAllMembersLoaded: true,
    }),
    reducers({
        members: [[] as unknown[], {}],
    }),
])
