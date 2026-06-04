import {
    IconApp,
    IconCursorClick,
    IconFlag,
    IconHandMoney,
    IconPhone,
    IconSearch,
    IconThumbsDown,
    IconUser,
    IconVideoCamera,
} from '@posthog/icons'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType, PropertyOperator, ReplayTemplateType } from '~/types'

export const replayTemplates: ReplayTemplateType[] = [
    {
        key: 'signup-flow',
        name: 'Signup flow',
        description: 'Watch how users sign up for your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Signup page URL',
                key: 'signup-page-url',
                value: '/signup',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2B'],
        icon: <IconUser />,
    },
    {
        key: 'pricing-page',
        name: 'Pricing page',
        description: 'Watch how users navigate your pricing page. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Pricing page URL',
                key: 'pricing-page-url',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2B'],
        icon: <IconHandMoney />,
    },
    {
        key: 'upgrade-flow',
        name: 'Upgrade / subscribe flow',
        description:
            'Watch how users upgrade to the paid plan on your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Upgrade / subscribe page URL',
                key: 'upgrade-subscribe-page-url',
                description: 'Complete or partial URL',
            },
            {
                type: 'event',
                name: 'Upgrade / subscribe event',
                key: 'upgrade-subscribe-event',
                description: 'The event that triggers the upgrade / subscribe flow.',
            },
        ],
        categories: ['B2B'],
        icon: <IconHandMoney />,
    },
    {
        key: 'onboarding-flow',
        name: 'Onboarding flow',
        description: 'Watch how users onboard to your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Onboarding page URL',
                key: 'onboarding-page-url',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2B'],
        icon: <IconApp />,
    },
    {
        key: 'feature-usage',
        name: 'Feature usage',
        description:
            'Think of a feature you want to improve. Watch how users interact with it, and see where they get stuck.',
        variables: [
            {
                type: 'event',
                name: 'Feature event',
                key: 'feature-event',
                description: 'The event that indicates a user has interacted with the feature.',
            },
            {
                type: 'pageview',
                name: 'Feature page URL',
                key: 'feature-page-url',
                description: 'Complete or partial URL where the feature is located.',
            },
        ],
        categories: ['B2B', 'B2C'],
        icon: <IconCursorClick />,
    },
    {
        key: 'purchase-flow',
        name: 'Purchase flow',
        description: 'Watch how users purchase from your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'pageview',
                name: 'Purchase page URL',
                key: 'purchase-page-url',
                description: 'Complete or partial URL',
            },
        ],
        categories: ['B2C'],
        icon: <IconHandMoney />,
    },
    {
        key: 'product-search',
        name: 'Product search',
        description:
            'Watch how users search for products on your website. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'event',
                name: 'Product search event',
                key: 'product-search-event',
                description: 'The event that indicates a user has searched for something on your website.',
            },
        ],
        categories: ['B2C'],
        icon: <IconSearch />,
    },
    {
        key: 'experiment',
        name: 'A/B test results',
        description: 'Watch how users interact with your A/B test. Look for any areas or steps that cause friction.',
        variables: [
            {
                type: 'flag',
                name: 'Feature flag',
                key: 'feature-flag',
                description: 'The feature flag that you want to observe.',
            },
        ],
        categories: ['More'],
        icon: <IconFlag />,
    },
    {
        key: 'rageclicks',
        name: 'Rageclicks',
        description: 'See where users are "rageclicking" on your website to find things that don\'t work as expected.',
        variables: [
            {
                type: 'event',
                name: 'Rageclick event',
                key: 'rageclick-event',
                description: 'The event that indicates a user has "rageclicked" on your website.',
                noTouch: true,
                filterGroup: {
                    id: '$rageclick',
                    name: '$rageclick',
                    type: TaxonomicFilterGroupType.Events,
                },
            },
        ],
        categories: ['More'],
        icon: <IconThumbsDown />,
    },
    {
        key: 'scattershot',
        name: 'Scattershot',
        description: 'Watch all recent replays, and see where users are getting stuck.',
        variables: [],
        categories: ['More'],
        order: 'start_time',
        icon: <IconVideoCamera />,
    },
    {
        key: 'person-property',
        name: 'Person property',
        description: 'Watch all replays for users with a specific property, like a specific email address.',
        variables: [
            {
                type: 'person-property',
                name: 'Person property',
                key: 'person-property',
                description: 'The person property that you want to observe.',
            },
        ],
        categories: ['More'],
        icon: <IconUser />,
    },
    {
        key: 'mobile-devices',
        name: 'Mobile devices',
        description: 'Watch replays from mobile device web browsers to look for problems with your responsive design.',
        variables: [
            {
                type: 'snapshot_source',
                name: 'Mobile device',
                key: 'mobile-device',
                description: 'Users who used your website on a mobile device.',
                noTouch: true,
                filterGroup: {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    properties: [
                        {
                            key: '$screen_width',
                            value: '600',
                            operator: PropertyOperator.LessThan,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
            },
        ],
        categories: ['More'],
        icon: <IconPhone />,
    },
    {
        key: 'activity-score',
        name: 'Most active users',
        description: 'Watch recordings of the most active sessions. Lots of valuable insights, guaranteed!',
        order: 'activity_score',
        categories: ['More'],
        icon: <IconCursorClick />,
    },
]
