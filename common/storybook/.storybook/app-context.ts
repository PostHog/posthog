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
    has_pageview: true,
    has_screen: true,
    has_person_email: false,
    persisted_feature_flags: [],
    commit_sha: undefined,
    preflight: null as any, // `null` triggers a fetch and lets us mock the data
    switched_team: null,
    oauth_application: {
        client_id: 'storybook-client-id',
        name: 'Storybook OAuth App',
        is_verified: false,
        logo_uri: null,
    },
    resource_access_control: {
        action: 'manager',
        data_catalog: 'manager',
        feature_flag: 'manager',
        hog_flow: 'manager',
        heatmap: 'manager',
        dashboard: 'manager',
        dashboard_template: 'manager',
        insight: 'manager',
        notebook: 'manager',
        session_recording: 'manager',
        sharing_configuration: 'manager',
        revenue_analytics: 'manager',
        survey: 'manager',
        ticket: 'manager',
        experiment: 'manager',
        export: 'manager',
        early_access_feature: 'manager',
        external_data_source: 'manager',
        web_analytics: 'manager',
        activity_log: 'viewer',
        customer_analytics: 'manager',
        llm_analytics: 'manager',
        evaluation: 'manager',
        llm_playground: 'manager',
        mcp_analytics: 'manager',
        tagger: 'manager',
        llm_skill: 'manager',
        toolbar: 'viewer',
        error_tracking: 'manager',
        metrics: 'manager',
        replay_scanner: 'manager',
        stamphog: 'manager',
    },
})
