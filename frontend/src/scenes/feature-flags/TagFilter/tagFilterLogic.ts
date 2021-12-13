import { kea } from 'kea'
import api from 'lib/api'

export const tagFilterLogic = kea({
    path: ['scenes', 'feature-flags', 'Tagfilter', 'tagFilterLogic'],

    actions: {
        setUsername: (username) => ({ username }),
    },

    reducers: {
        username: [
            'keajs',
            {
                setUsername: (_, payload) => payload.username,
            },
        ],
    },
})

// export const tagFilterLogic = kea({
//     actions: {
//         loadUsers: true,
//         loadUsersSuccess: (users) => ({ users }),
//         loadUsersFailure: (error) => ({ error }),
//     },

//     reducers: {
//         users: [
//             [],
//             {
//                 loadUsersSuccess: (_, { users }) => users,
//             },
//         ],
//         usersLoading: [
//             false,
//             {
//                 loadUsers: () => true,
//                 loadUsersSuccess: () => false,
//                 loadUsersFailure: () => false,
//             },
//         ],
//         usersError: [
//             null,
//             {
//                 loadUsers: () => null,
//                 loadUsersFailure: (_, { error }) => error,
//             },
//         ],
//     },

//     listeners: ({ actions }) => ({
//         loadUsers: async () => {
//             try {
//                 const users = await api.get('users')
//                 actions.loadUsersSuccess(users)
//             } catch (error: unknown) {
//                 actions.loadUsersFailure(error.message)
//             }
//         },
//     }),
// })
