// This should eventually be moved to a DB.
export interface story {
    id: string
    title: string
    thumbnailUrl: string
    description?: string
    mediaUrl: string
    type: 'image' | 'video'
    durationMs?: number
    link?: string
}

export interface storyGroup {
    id: string
    title: string
    stories: story[]
}

// NOTE: The order of the stories is important. The first story in each group is the one that is shown when the group is clicked
// from top to bottom.
// Important: we use the first thumbnail of the first story in each group as the thumbnail of the group.
export const storiesMap: storyGroup[] = [
    {
        id: 'changelog',
        title: 'Changelog',
        stories: [
            {
                id: 'changelog_save_filters_replay_1',
                title: 'Changelog',
                description: 'Save filters for session replay',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_save_filters_replay_wide_684b8b7844_82b2ffd07c.mp4',
                type: 'video',
                durationMs: 29000,
            },
            {
                id: 'changelog_linear_share_1',
                title: 'Changelog',
                description: 'Share session replays on Linear',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_linear_share_wide_0d3520bba5_64049c56b6.mp4',
                type: 'video',
                durationMs: 44000,
            },
            {
                id: 'changelog_cta',
                title: 'Changelog',
                description: 'Read our changelog!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/changelog_cta_f8c6037283.png',
                type: 'image',
                durationMs: 5500,
            },
        ],
    },
    {
        id: 'toolbar',
        title: 'Toolbar',
        stories: [
            {
                id: 'toolbar_overview_1',
                title: 'Toolbar',
                description: 'Overview of the toolbar',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_wide_5df781bfb4_e455df0d27.mp4',
                type: 'video',
                durationMs: 41000,
            },
            {
                id: 'toolbar_actions_1',
                title: 'Toolbar',
                description: 'Create actions',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_actions_wide_fbe2f78e7e_e60dd23156.mp4',
                type: 'video',
                durationMs: 45000,
            },
            {
                id: 'toolbar_inspect_1',
                title: 'Toolbar',
                description: 'Inspect elements',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_inspect_a284324d14_24631f27fd.png',
                type: 'image',
            },
            {
                id: 'toolbar_heatmap_1',
                title: 'Toolbar',
                description: 'View heatmaps',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_heatmap_460f46f86b_04862b4e0a.png',
                type: 'image',
            },
            {
                id: 'toolbar_feature_flags_1',
                title: 'Toolbar',
                description: 'Flip feature flags',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_feature_flags_31802301a3_41dacb9996.png',
                type: 'image',
            },
            {
                id: 'toolbar_events_1',
                title: 'Toolbar',
                description: 'Debug events',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_debug_events_90dcef3c7b_b7564ce9af.png',
                type: 'image',
            },
            {
                id: 'toolbar_web_vitals_1',
                title: 'Toolbar',
                description: 'Check web vitals',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_web_vitals_0150d8d8ca_6b9a790fb1.png',
                type: 'image',
            },
            {
                id: 'toolbar_experiments_1',
                title: 'Toolbar',
                description: 'Create experiments',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_experiments_6745bae143_b82232edde.png',
                type: 'image',
            },
            {
                id: 'cool_features_1',
                title: 'Toolbar',
                description: 'Check out hedgehog mode!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_cool_features_357aa7fc36_dc294f7fca.png',
                type: 'image',
            },
        ],
    },
    {
        id: 'deskhog',
        title: 'DeskHog',
        stories: [
            {
                id: 'deskhog',
                title: 'DeskHog',
                description: 'Open-source, 3D-printed, palm-sized',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_7d6d55ea31.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_wide_5df781bfb4_e455df0d27.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'max-ai',
        title: 'Max AI',
        stories: [
            {
                id: 'max-ai-overview',
                title: 'Max AI',
                description: 'Say hi to Max!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/max_ai_f8c9cdf4e8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/placeholder_hogtok_743c5dde0e.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'product-analytics',
        title: 'Product analytics',
        stories: [
            {
                id: 'product-analytics-overview',
                title: 'Product analytics',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/product_analytics_icon_eb743fa24b.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/placeholder_hogtok_2_6da6e7d3d0.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'web-analytics',
        title: 'Web analytics',
        stories: [
            {
                id: 'web-analytics-overview',
                title: 'Web analytics',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/web_analytics_700d89898c.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/placeholder_hogtok_3_d7e99120b4.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'session-replay',
        title: 'Session replay',
        stories: [
            {
                id: 'session-replay-overview',
                title: 'Session replay',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/session_replay_5cd544fd6e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/placeholder_screen_4_ceb3e8b201.png',
                type: 'image',
                durationMs: 6000,
            },
        ],
    },
    {
        id: 'feature-flags',
        title: 'Feature flags',
        stories: [
            {
                id: 'feature-flags-overview',
                title: 'Feature flags',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flags_65f86819c0.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/screensaver_bouncing_logo_f91aed8237.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'experiments',
        title: 'Experiments',
        stories: [
            {
                id: 'Give Andy, Javier, and Edwin feedback!',
                title: 'Experiments',
                description: 'Give us feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/experiments_473107c5b2.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/placeholder_hogtok_743c5dde0e.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'surveys',
        title: 'Surveys',
        stories: [
            {
                id: 'surveys-overview',
                title: 'Surveys',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/surveys_ba81894d25.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/placeholder_hogtok_2_6da6e7d3d0.mp4',
                type: 'video',
            },
        ],
    },
    {
        id: 'data-pipelines',
        title: 'Data pipelines',
        stories: [
            {
                id: 'data-pipelines-overview',
                title: 'Data pipelines',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/data_pipelines_cfed9a24c9.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/placeholder_hogtok_3_d7e99120b4.mp4',
                type: 'video',
                durationMs: 6000,
            },
        ],
    },
    {
        id: 'data-warehouse',
        title: 'Data warehouse',
        stories: [
            {
                id: 'data-warehouse-overview',
                title: 'Data warehouse',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/data_warehouse_edc03a4e0b.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/placeholder_screen_4_ceb3e8b201.png',
                type: 'image',
            },
        ],
    },
    {
        id: 'llm-observability',
        title: 'LLM observability',
        stories: [
            {
                id: 'LLM-observability-overview',
                title: 'LLM observability',
                description: 'Give Andy, Javier, and Edwin feedback!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/llm_observability_d5b8320de9.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/screensaver_bouncing_logo_f91aed8237.mp4',
                type: 'video',
            },
        ],
    },
]
