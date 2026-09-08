import { CampaignConfig } from './types'

export const lennySummitCampaign: CampaignConfig = {
    name: 'Lenny & Friends Summit',
    heroTitle: 'Get $200 in PostHog credit',
    heroSubtitle: 'An offer for Lenny & Friends Summit attendees',
    benefits: [
        {
            title: '$200 in PostHog credit',
            description: 'The credit comes off your PostHog invoices automatically once you redeem your code.',
        },
        {
            title: 'Spend it on any product',
            description:
                'Product analytics, session replay, experiments, surveys, feature flags, error tracking, data warehouse - whatever you need to ship, measure, and improve your product.',
        },
        {
            title: '12-month access',
            description: 'The credit is valid for one year from the day you redeem your code.',
        },
    ],
    eligibilityCriteria: [
        'A code from the Lenny & Friends Summit',
        'Organization admin or owner in PostHog',
        'An active PostHog subscription',
    ],
    footerNote: 'Already redeemed the Lenny Product Pass? This credit stacks with it.',
}
