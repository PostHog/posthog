// This should eventually be moved to a DB.

export enum StoryType {
    Image = 'image',
    Video = 'video',
    Overlay = 'overlay',
}

export enum CloseOverlayAction {
    Overlay = 'overlay',
    Modal = 'modal',
    Next = 'next',
    Previous = 'previous',
}

export enum ArrowIcon {
    Right = 'right',
    Up = 'up',
}

export interface SeeMoreOptions {
    arrowIcon?: ArrowIcon
    backgroundColor?: 'black' | 'white'
    hideDefaultClose?: boolean
    text?: string
    textColor?: 'black' | 'white'
}

export interface story {
    id: string
    title: string
    thumbnailUrl: string
    description?: string
    mediaUrl?: string
    type: StoryType
    durationMs?: number
    seeMoreLink?: string
    seeMoreOverlay?: (closeOverlay: (action?: CloseOverlayAction) => void) => JSX.Element
    seeMoreOptions?: SeeMoreOptions
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
                type: StoryType.Video,
            },
            {
                id: 'changelog_linear_share_1',
                title: 'Changelog',
                description: 'Share session replays on Linear',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_linear_share_wide_0d3520bba5_64049c56b6.mp4',
                type: StoryType.Video,
            },
            {
                id: 'overlay_example',
                title: 'Changelog',
                description: 'New feature showcase with component overlay',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/changelog_cta_f8c6037283.png',
                type: StoryType.Image,
                seeMoreLink: 'https://posthog.com/changelog',
                seeMoreOptions: {
                    backgroundColor: 'black',
                },
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
                type: StoryType.Video,
                durationMs: 41000,
            },
            {
                id: 'toolbar_actions_1',
                title: 'Toolbar',
                description: 'Create actions',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_actions_wide_fbe2f78e7e_e60dd23156.mp4',
                type: StoryType.Video,
                durationMs: 45000,
            },
            {
                id: 'toolbar_inspect_1',
                title: 'Toolbar',
                description: 'Inspect elements',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_inspect_a284324d14_24631f27fd.png',
                type: StoryType.Image,
            },
            {
                id: 'toolbar_heatmap_1',
                title: 'Toolbar',
                description: 'View heatmaps',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_heatmap_460f46f86b_04862b4e0a.png',
                type: StoryType.Image,
            },
            {
                id: 'toolbar_feature_flags_1',
                title: 'Toolbar',
                description: 'Flip feature flags',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_feature_flags_31802301a3_41dacb9996.png',
                type: StoryType.Image,
            },
            {
                id: 'toolbar_events_1',
                title: 'Toolbar',
                description: 'Debug events',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_debug_events_90dcef3c7b_b7564ce9af.png',
                type: StoryType.Image,
            },
            {
                id: 'toolbar_web_vitals_1',
                title: 'Toolbar',
                description: 'Check web vitals',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_web_vitals_0150d8d8ca_6b9a790fb1.png',
                type: StoryType.Image,
            },
            {
                id: 'toolbar_experiments_1',
                title: 'Toolbar',
                description: 'Create experiments',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_experiments_6745bae143_b82232edde.png',
                type: StoryType.Image,
            },
            {
                id: 'cool_features_1',
                title: 'Toolbar',
                description: 'Check out hedgehog mode!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_cool_features_357aa7fc36_dc294f7fca.png',
                type: StoryType.Image,
            },
        ],
    },
]
