import { CampaignConfig } from './types'

export const lennySummitCampaign: CampaignConfig = {
    name: 'Lenny & Friends Summit',
    heroTitle: 'Get $200 in PostHog credit',
    heroSubtitle: 'A Lenny & Friends Summit giveaway',
    benefits: [
        {
            title: '$200 in PostHog credit',
            description: 'Use the credit toward future PostHog invoices after you activate billing.',
        },
        {
            title: 'Spend it on any product',
            description:
                'Product analytics, session replay, experiments, surveys, feature flags, error tracking, and the rest.',
        },
        {
            title: 'Valid for 12 months',
            description: 'The credit lasts a year from the day you redeem your code.',
        },
    ],
    eligibilityCriteria: [
        'A valid code from the Lenny & Friends Summit',
        'Organization admin or owner in PostHog',
        'An active PostHog subscription',
    ],
    footerNote: 'Already redeemed the Lenny Product Pass? This credit stacks with it.',
}
