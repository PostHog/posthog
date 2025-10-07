import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { AppContext } from '~/types'

export const getStorybookAppContext = (): AppContext => ({
    anonymous: false,
    // Ideally we wouldn't set `current_team` here, the same way we don't set `current_user`, but unfortunately
    // as of March 2024, a bunch of logics make the assumption that this is set, via `AppConfig`
    current_team: MOCK_DEFAULT_TEAM,
    current_project: MOCK_DEFAULT_PROJECT,
    current_user: undefined as any, // `undefined` triggers a fetch and lets us mock the data
    default_event_name: '$pageview',
    persisted_feature_flags: [],
    commit_sha: undefined,
    preflight: null as any, // `null` triggers a fetch and lets us mock the data
    switched_team: null,
    resource_access_control: {
        action: 'manager',
        feature_flag: 'manager',
        dashboard: 'manager',
        insight: 'manager',
        notebook: 'manager',
        session_recording: 'manager',
        revenue_analytics: 'manager',
        experiment: 'manager',
    },
})
