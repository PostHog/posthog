import { kea } from 'kea'
import api from './Api'

export const userLogic = kea({
  actions: () => ({
    loadUser: true,
    updateUser: update => ({ update }),
    setUser: user => ({ user: { ...user } }) // make and use a copy of user to patch some legacy issues
  }),

  reducers: ({ actions }) => ({
    user: [null, {
      [actions.setUser]: (_, payload) => payload.user
    }]
  }),

  events: ({ actions }) => ({
    afterMount: actions.loadUser
  }),

  listeners: ({ actions }) => ({
    [actions.loadUser]: async () => {
      try {
        const user = await api.get('api/user')
        actions.setUser(user)

        if (user && user.id) {
          window.Sentry && window.Sentry.setUser({ email: user.email, id: user.id });
          window.posthog && window.posthog.identify(user.distinct_id);
        }
      } catch (error) {
        actions.setUser(null)
      }
    },
    [actions.updateUser]: async ({ update }) => {
      try {
        const user = await api.update('api/user', update)
        actions.setUser(user);
      } catch (error) {
        console.error('TODO! Unhandled error')
        // actions.setUser(null)
      }
    }
  })
})
