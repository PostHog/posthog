import { AppContext } from '~/types'

export const getStorybookAppContext = (): AppContext => ({
    anonymous: false,
    current_team: null, // null triggers a fetch and lets us mock the data
    current_user: undefined as any, // undefined triggers a fetch and lets us mock the data
    default_event_name: '$pageview',
    persisted_feature_flags: [],
    commit_sha: undefined,
    preflight: null as any, // null triggers a fetch and lets us mock the data
    switched_team: null,
})
