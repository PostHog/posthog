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
export const storiesMap: storyGroup[] = [
    {
        id: 'changelog',
        title: 'Changelog',
        stories: [
            {
                id: 'changelog_save_filters_replay_1',
                title: 'Save filters for session replay',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/happy_2496675ac4.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_save_filters_replay_wide_684b8b7844_82b2ffd07c.mp4',
                type: 'video',
                durationMs: 29000,
            },
            {
                id: 'changelog_linear_share_1',
                title: 'Linear share',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/happy_2496675ac4.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_linear_share_wide_0d3520bba5_64049c56b6.mp4',
                type: 'video',
                durationMs: 44000,
            },
        ],
    },
    {
        id: 'toolbar',
        title: 'Toolbar',
        stories: [
            {
                id: 'toolbar_overview_1',
                title: 'Toolbar overview',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_wide_5df781bfb4_e455df0d27.mp4',
                type: 'video',
                durationMs: 41000,
            },
            {
                id: 'toolbar_actions_1',
                title: 'Toolbar actions',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_actions_wide_fbe2f78e7e_e60dd23156.mp4',
                type: 'video',
                durationMs: 45000,
            },
            {
                id: 'toolbar_inspect_1',
                title: 'Toolbar inspect',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_inspect_a284324d14_24631f27fd.png',
                type: 'image',
            },
            {
                id: 'toolbar_heatmap_1',
                title: 'Toolbar heatmap',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_heatmap_460f46f86b_04862b4e0a.png',
                type: 'image',
            },
            {
                id: 'toolbar_feature_flags_1',
                title: 'Toolbar feature flags',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_feature_flags_31802301a3_41dacb9996.png',
                type: 'image',
            },
            {
                id: 'toolbar_events_1',
                title: 'Toolbar debug events',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_debug_events_90dcef3c7b_b7564ce9af.png',
                type: 'image',
            },
            {
                id: 'toolbar_web_vitals_1',
                title: 'Toolbar web vitals',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_web_vitals_0150d8d8ca_6b9a790fb1.png',
                type: 'image',
            },
            {
                id: 'toolbar_experiments_1',
                title: 'Toolbar experiments',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_experiments_6745bae143_b82232edde.png',
                type: 'image',
            },
            {
                id: 'toolbar_web_vitals_2',
                title: 'Cool features',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_cool_features_357aa7fc36_dc294f7fca.png',
                type: 'image',
            },
        ],
    },
]
