import { CampaignConfig } from './types'

export const communityCampaign: CampaignConfig = {
    name: 'PostHog community points',
    heroTitle: 'Redeem your community points',
    heroSubtitle: 'Your code is worth $25 in PostHog credit for this organization.',
    benefits: [
        {
            title: '$25 PostHog credit',
            description: 'Applied to your next invoices. Valid for 12 months. Not for AI products.',
        },
    ],
    eligibilityCriteria: [
        'You received a code from the PostHog community team',
        'This organization has an active subscription',
        'You are an admin or owner of this organization',
    ],
    footerNote: 'To claim for a different organization, switch to that organization first. One code per organization.',
}
