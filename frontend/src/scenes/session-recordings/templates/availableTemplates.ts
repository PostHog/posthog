import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { ReplayTemplateType } from '~/types'

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
        ],
        categories: ['B2B', 'B2C'],
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
    },
    {
        key: 'scattershot',
        name: 'Scattershot',
        description: 'Watch all recent replays, and see where users are getting stuck.',
        variables: [],
        categories: ['More'],
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
    },
]
