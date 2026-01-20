import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { UserProductListReason } from '~/queries/schema/schema-general'
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
    custom_products: [
        {
            id: 'product-1',
            product_path: 'Product analytics',
            enabled: true,
            reason: UserProductListReason.USED_BY_COLLEAGUES,
            reason_text: null,
            created_at: new Date().toISOString(), // Recent, should show green dot
            updated_at: new Date().toISOString(),
        },
        {
            id: 'product-2',
            product_path: 'Session replay',
            enabled: true,
            reason: UserProductListReason.NEW_PRODUCT,
            reason_text: 'This is a brand new product we just launched!',
            created_at: new Date().toISOString(), // Recent, should show green dot
            updated_at: new Date().toISOString(),
        },
        {
            id: 'product-3',
            product_path: 'Feature flags',
            enabled: true,
            reason: UserProductListReason.USED_ON_SEPARATE_TEAM, // Should NOT show green dot
            reason_text: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        },
        {
            id: 'product-4',
            product_path: 'Dashboards',
            enabled: true,
            reason: UserProductListReason.SALES_LED,
            reason_text: null,
            created_at: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10 days ago, should NOT show dot
            updated_at: new Date().toISOString(),
        },
        {
            id: 'product-5',
            product_path: 'Experiments',
            enabled: true,
            reason: UserProductListReason.USED_SIMILAR_PRODUCTS,
            reason_text: null,
            created_at: new Date().toISOString(), // Recent, should show green dot
            updated_at: new Date().toISOString(),
        },
    ],
    resource_access_control: {
        action: 'manager',
        feature_flag: 'manager',
        dashboard: 'manager',
        insight: 'manager',
        notebook: 'manager',
        session_recording: 'manager',
        revenue_analytics: 'manager',
        survey: 'manager',
        experiment: 'manager',
        external_data_source: 'manager',
        web_analytics: 'manager',
        activity_log: 'viewer',
    },
})
