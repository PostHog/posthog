// This should eventually be moved to a DB.
import { PizzaSurveyOverlayComponent } from './PizzaSurveyOverlayComponent'

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
    aspectRatio?: '4:3' | '16:9' | 'auto'
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
        id: 'surveys',
        title: 'Surveys',
        stories: [
            {
                id: 'surveys-overview',
                title: 'Surveys',
                description: 'Ask users for feedback',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/surveys_522e544094.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/surveys_overview_2cfc290333.mp4',
                type: StoryType.Video,
            },
            {
                id: 'surveys-cta',
                title: 'Surveys',
                description: 'Try surveys',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/surveys_522e544094.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/surveys_cta_b32a2b0596.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/surveys',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Create a survey',
                },
            },
            {
                id: 'surveys-pineapple-pizza-poll',
                title: 'Surveys',
                description: "There's only one right answer!",
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/surveys_522e544094.png',
                type: StoryType.Overlay,
                seeMoreOverlay: (closeOverlay) => <PizzaSurveyOverlayComponent closeOverlay={closeOverlay} />,
                seeMoreOptions: {
                    hideDefaultClose: true,
                },
            },
        ],
    },
    {
        id: 'experiments',
        title: 'Experiments',
        stories: [
            {
                id: 'experiments-overview',
                title: 'Experiments',
                description: 'Find out what performs',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/experiments_icon_05539e123f.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/experiments_overview_193828c533.mp4',
                type: StoryType.Video,
            },
            {
                id: 'experiments-cta',
                title: 'Experiments',
                description: 'Try experiments',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/experiments_icon_05539e123f.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/experiments_cta_18e8927447.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/experiments',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Create an experiment',
                },
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
                description: 'Roll out changes',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flags_fd5d9949a0.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/feature_flags_overview_79e6f410ae.mp4',
                type: StoryType.Video,
            },
            {
                id: 'feature-flags-cta',
                title: 'Feature flags',
                description: 'Try feature flags',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flags_fd5d9949a0.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/feature_flags_cta_image_3c1f74f6ed.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/feature_flags',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Get started',
                },
            },
        ],
    },
    {
        id: 'max-ai',
        title: 'Max AI',
        stories: [
            {
                id: 'meet-max-ai-overview',
                title: 'Max AI',
                description: 'Say hi to Max!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/max_ai_f8c9cdf4e8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/meet_max_ai_overview_778f4acffb.mp4',
                type: StoryType.Video,
            },
            {
                id: 'max-ai-cta',
                title: 'Max AI',
                description: 'Try talking to Max',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/max_ai_f8c9cdf4e8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/max_cta_frame_06906e3804.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/#panel=max:hi%20max',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Say hi',
                },
            },
        ],
    },
    {
        id: 'changelog',
        title: 'Changelog',
        stories: [
            {
                id: 'changelog-55-cdp-destinations',
                title: 'Changelog',
                description: '55 new CDP destinations',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_cdp_destinations_158c35a2b8.mp4',
                type: StoryType.Video,
            },
            {
                id: 'changelog-hog-templating',
                title: 'Changelog',
                description: 'In-app Hog templating',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_hog_templating_e21396dadf.mp4',
                type: StoryType.Video,
            },
            {
                id: 'changelog-linear-share-modal',
                title: 'Changelog',
                description: 'Share session replays on Linear',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_linear_share_4d21aef711.mp4',
                type: StoryType.Video,
            },
            {
                id: 'changelog-save-filters-session-replay',
                title: 'Changelog',
                description: 'Save filters for session replay',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/video/upload/changelog_save_filters_replay_59939f9908.mp4',
                type: StoryType.Video,
            },
            {
                id: 'changelog-cta',
                title: 'Changelog',
                description: 'New feature showcase with component overlay',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_phone_9f7523e1a8.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/changelog_cta_f8c6037283.png',
                type: StoryType.Image,
                seeMoreLink: 'https://posthog.com/changelog',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'See more updates',
                },
            },
        ],
    },
    {
        id: 'toolbar',
        title: 'Toolbar',
        stories: [
            {
                id: 'toolbar-overview',
                title: 'Toolbar',
                description: 'Overview of the toolbar',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_overview_2320038fa8.mp4',
                type: StoryType.Video,
            },
            {
                id: 'toolbar-create-actions',
                title: 'Toolbar',
                description: 'Create actions',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/toolbar_actions_e0d6b18b99.mp4',
                type: StoryType.Video,
            },
            {
                id: 'toolbar-inspect-image',
                title: 'Toolbar',
                description: 'Inspect elements',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_inspect_a284324d14_24631f27fd.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
            {
                id: 'toolbar-heatmap-image',
                title: 'Toolbar',
                description: 'View heatmaps',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_heatmap_460f46f86b_04862b4e0a.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
            {
                id: 'toolbar-feature-flags-image',
                title: 'Toolbar',
                description: 'Flip feature flags',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_feature_flags_31802301a3_41dacb9996.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
            {
                id: 'toolbar-events-image',
                title: 'Toolbar',
                description: 'Debug events',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_debug_events_90dcef3c7b_b7564ce9af.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
            {
                id: 'toolbar-web-vitals-image',
                title: 'Toolbar',
                description: 'Check web vitals',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_web_vitals_0150d8d8ca_6b9a790fb1.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
            {
                id: 'toolbar-experiments-image',
                title: 'Toolbar',
                description: 'Create experiments',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_experiments_6745bae143_b82232edde.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
            {
                id: 'toolbar-cool-features-image',
                title: 'Toolbar',
                description: 'Check out hedgehog mode!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hoggie_builder_dc64451e64.png',
                mediaUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/toolbar_cool_features_357aa7fc36_dc294f7fca.png',
                type: StoryType.Image,
                seeMoreLink: 'https://app.posthog.com/toolbar',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Launch the toolbar',
                },
            },
        ],
    },
    {
        id: 'deskhog',
        title: 'DeskHog',
        stories: [
            {
                id: 'deskhog-minidoc',
                title: 'DeskHog',
                description: 'Open-source, 3D-printed, palm-sized',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_7d6d55ea31.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/deskhog_minidoc_ea362ae944.mp4',
                type: StoryType.Video,
            },
            {
                id: 'deskhog-infomercial',
                title: 'DeskHog',
                description: 'ORDER NOW!',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_7d6d55ea31.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/deskhog_infomercial_a50a1dd4ec.mp4',
                type: StoryType.Video,
                aspectRatio: '4:3',
            },
            {
                id: 'deskhog-kit',
                title: 'DeskHog',
                description: 'Open-source, 3D-printed, palm-sized',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_7d6d55ea31.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_kit_657f1da249.png',
                seeMoreLink: 'https://posthog.com/deskhog',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Get your own',
                },
                type: StoryType.Image,
            },
            {
                id: 'deskhog-colors',
                title: 'DeskHog',
                description: 'Open-source, 3D-printed, palm-sized',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_7d6d55ea31.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_colors_84c91ae075.png',
                seeMoreLink: 'https://posthog.com/deskhog',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Get your own',
                },
                type: StoryType.Image,
            },
            {
                id: 'deskhog-cta',
                title: 'DeskHog',
                description: 'Open-source, 3D-printed, palm-sized',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_7d6d55ea31.png',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/deskhog_cta_513a9e19f4.png',
                seeMoreLink: 'https://posthog.com/deskhog',
                seeMoreOptions: {
                    backgroundColor: 'black',
                    text: 'Get your own',
                },
                type: StoryType.Image,
            },
        ],
    },
]
