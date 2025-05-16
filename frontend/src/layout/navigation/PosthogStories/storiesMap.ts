export interface story {
    id: string
    title: string
    thumbnailUrl: string
    description?: string
    mediaUrl: string
    type: 'image' | 'video'
    durationMs?: number
    link?: string
    order: number
}

export interface storyGroup {
    id: string
    title: string
    stories: story[]
    order: number
}

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
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_save_filters_replay_1_9aabb9799c.mp4',
                type: 'video',
                link: 'https://picsum.photos/id/1011/400/600',
                durationMs: 29000,
                order: 1,
            },
            {
                id: 'changelog_linear_share_1',
                title: 'Linear share',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/happy_2496675ac4.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_linear_share_1_11fdaee4cd.mp4',
                type: 'video',
                link: 'https://picsum.photos/id/1012/400/600',
                durationMs: 44000,
                order: 2,
            },
        ],
        order: 1,
    },
    {
        id: 'toolbar',
        title: 'Toolbar',
        stories: [
            {
                id: 'toolbar_overview_1',
                title: 'Toolbar overview',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_2_0a34e62550.mp4',
                type: 'video',
                durationMs: 41000,
                link: 'https://picsum.photos/id/1025/400/600',
                order: 1,
            },
            {
                id: 'toolbar_actions_1',
                title: 'Toolbar actions',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_actions_07e751a76a.mp4',
                type: 'video',
                durationMs: 45000,
                link: 'https://picsum.photos/id/1035/400/600',
                order: 2,
            },
            {
                id: 'toolbar_inspect_1',
                title: 'Toolbar inspect',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_inspect_a43e85f7d3.png',
                type: 'image',
                order: 3,
            },
            {
                id: 'toolbar_heatmap_1',
                title: 'Toolbar heatmap',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_heatmap_d68abfa438.png',
                type: 'image',
                order: 4,
            },
            {
                id: 'toolbar_heatmap_2',
                title: 'Toolbar heatmap',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_feature_flags_6723eb2704.png',
                type: 'image',
                order: 5,
            },
            {
                id: 'toolbar_events_1',
                title: 'Toolbar events',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_events_32332c188c.png',
                type: 'image',
                order: 6,
            },
            {
                id: 'toolbar_web_vitals_1',
                title: 'Toolbar web vitals',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_web_vitals_a21e2b2956.png',
                type: 'image',
                order: 7,
            },
            {
                id: 'toolbar_web_vitals_2',
                title: 'Toolbar web vitals',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flag_12cb052a7e.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_cool_features_f4e9a08d4c.png',
                type: 'image',
                order: 8,
            },
        ],
        order: 2,
    },
    {
        id: 'Tulum 2025',
        title: 'Tulum 2025',
        order: 4,
        stories: [
            {
                id: 'tulum_2025_1',
                title: 'Tulum 2025',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/relax_c82945b849.png',
                description: 'Amzing experience with the team in Tulum',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/new_version_tulum_2025_bd19fe7001.mov',
                type: 'video',
                order: 1,
                durationMs: 64000,
            },
        ],
    },
]
