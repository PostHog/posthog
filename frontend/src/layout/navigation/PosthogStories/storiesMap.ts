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
        ],
        order: 2,
    },
    {
        id: 'Hackathon 2024',
        title: 'Hackathon 2024',
        order: 3,
        stories: [
            {
                id: 'hackathon_2024_1',
                title: 'RealTimeHog 3000',
                thumbnailUrl:
                    'https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2024_05_31_at_9_53_45_AM_86d275de54.png',
                description: 'Seeing people using your product live boosts dopamine levels.',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/realtime1_f40652b636.gif',
                type: 'image',
                order: 1,
            },
            {
                id: 'hackathon_2024_2',
                title: 'The presidential briefing',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hackathon_president_73aa5ced1a.png',
                description: 'AI-generated briefing, tailored to each individual team member and their interests.',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hackathon_president_73aa5ced1a.png',
                type: 'image',
                order: 2,
            },
            {
                id: 'hackathon_2024_3',
                title: '10x terms',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hackathon_dpyay_53b6334a36.png',
                description: 'We summarized our terms and privacy policy in plain English.',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hackathon_dpyay_53b6334a36.png',
                type: 'image',
                order: 3,
            },
            {
                id: 'hackathon_2024_4',
                title: 'ZenHog',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/supporthog_9bf5751e2a.gif',
                description: 'Customer support product.',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/supporthog_9bf5751e2a.gif',
                type: 'image',
                order: 4,
            },
            {
                id: 'hackathon_2024_5',
                title: 'The referral scheme',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/referralscheme_d3c3622d48.png',
                description: 'Everyone loves a pyramid scheme, right?!',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/referralscheme_d3c3622d48.png',
                type: 'image',
                order: 5,
            },
            {
                id: 'hackathon_2024_6',
                title: 'Managed reverse proxy',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/reverseproxies_36abec68b3.png',
                description:
                    'Everyone loves ad-blockers. But, for a lot of our customers, they stop data from reaching PostHog.',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/reverseproxies_36abec68b3.png',
                type: 'image',
                order: 6,
            },
            {
                id: 'hackathon_2024_7',
                title: 'A/B TestHog',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/abtesthog1_eef0030d9b.png',
                description: 'Want to know how to improve your website but don’t know where to start? ',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/abtesthog1_eef0030d9b.png',
                type: 'image',
                order: 7,
            },
            {
                id: 'hackathon_2024_8',
                title: 'HERMES',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hermes1_275dc08370.jpg',
                description:
                    'This is effectively a database of user interviews, showing who was interviewed, who they work for, what they do, how much they pay for PostHog, the products they talked to us about, and an AI-generated summary of our user interview notes.',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/hermes1_275dc08370.jpg',
                type: 'image',
                order: 8,
            },
            {
                id: 'hackathon_2024_9',
                title: 'Data crunching',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/datacrunch1_7ab73f5ab4.jpg',
                description:
                    "We built a loading bar that includes live data on how much data we're crunching (database rows and data volume) and CPU usage we're deploying to generate an answer for you",
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/datacrunch1_7ab73f5ab4.jpg',
                type: 'image',
                order: 9,
            },
            {
                id: 'hackathon_2024_10',
                title: 'CLI',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/cli_fb71d1730d.png',
                description:
                    "We build products for engineers, so there's nothing better than bringing PostHog closer to their natural environment: the terminal.",
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/cli_fb71d1730d.png',
                type: 'image',
                order: 10,
            },
        ],
    },
    {
        id: 'Tulum 2025',
        title: 'Tulum 2025',
        order: 4,
        stories: [
            {
                id: 'tulum_2024_1',
                title: 'Tulum 2024',
                thumbnailUrl: 'https://res.cloudinary.com/dmukukwp6/image/upload/relax_c82945b849.png',
                description: 'Amzing experience with the team in Tulum',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/0515_85f1cca991.mov',
                type: 'video',
                order: 1,
                durationMs: 64000,
            },
        ],
    },
]
