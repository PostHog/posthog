import { Link } from '@posthog/lemon-ui'

import { CampaignConfig } from './types'

export const communityCampaign: CampaignConfig = {
    name: 'PostHog community',
    heroTitle: 'Get $30 in PostHog credit',
    heroSubtitle: 'A reward for your points in the PostHog community forum',
    benefits: [
        {
            title: '$30 in PostHog credit',
            description:
                'The credit applies to your future invoices before your card is charged. It does not expire, and you can spend it on any product.',
        },
    ],
    eligibilityCriteria: [
        'A valid code from the PostHog community store',
        'Organization admin or owner in PostHog',
        'An active PostHog subscription with a payment method on file',
        'At least one paid invoice. If you just added a card, you can redeem after your first invoice is paid.',
        'Up to three community codes per organization each month',
    ],
    allowsRepeatClaims: true,
    footerNote: (
        <>
            Problems redeeming? Email <Link to="mailto:community@posthog.com">community@posthog.com</Link>
        </>
    ),
}
