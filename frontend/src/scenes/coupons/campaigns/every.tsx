import { IconX } from '@posthog/icons'

import { Logo } from 'lib/brand/Logo'

import { CampaignConfig } from './types'

const EVERY_LOGO_BLACK = 'https://res.cloudinary.com/dmukukwp6/image/upload/every_black_d4ba0c3a4d.svg'
const EVERY_LOGO_WHITE = 'https://res.cloudinary.com/dmukukwp6/image/upload/every_white_438ee9fa45.svg'
// TODO: Keep this date in sync with EveryGoodieBagStrategy.INVOICE_CUTOFF_DATE in billing.
const EVERY_CREDIT_ELIGIBILITY_CUTOFF = 'July 14, 2026'

const EveryHero: React.FC = () => {
    return (
        <div className="flex items-center justify-center gap-3 mb-4">
            <Logo style={{ height: '3rem' }} />
            <IconX className="size-8 opacity-60" />
            <img src={EVERY_LOGO_BLACK} alt="EVERY" className="h-8 w-auto [filter:brightness(0)] dark:hidden" />
            <img src={EVERY_LOGO_WHITE} alt="EVERY" className="hidden h-8 w-auto dark:block" />
        </div>
    )
}

export const everyCampaign: CampaignConfig = {
    name: 'EVERY Goodie Bag',
    heroTitle: 'Up to $4K in PostHog credits for EVERY Goodie Bag customers',
    heroSubtitle:
        "$2K for PostHog's AI products for everyone, plus $2K in core product credits for new PostHog customers.",
    HeroImage: EveryHero,
    benefits: [
        {
            title: "$2K credits toward PostHog's AI products",
            description: (
                <>
                    All eligible EVERY Goodie Bag customers receive $2K in credits toward PostHog's AI products. Today,
                    that includes:
                    <ul className="mt-1 ml-4 list-disc text-muted text-sm">
                        <li>PostHog AI (including the Slack agent)</li>
                        <li>Inbox (self-driving PRs based on your data)</li>
                    </ul>
                </>
            ),
        },
        {
            title: "Early access to new features in PostHog's AI products",
            description:
                "Get access to select new products and features across PostHog's AI products as they become available.",
        },
        {
            title: '$2K PostHog core credits*',
            description: `New PostHog customers are also eligible for $2K in credits for PostHog core products, such as Product Analytics, Session Replay, Error Tracking, LLM Observability, and Data Warehouse.`,
        },
        {
            title: '12-month access',
            description: 'Campaign benefits run for one year from the day you redeem your code.',
        },
    ],
    eligibilityCriteria: [
        'Active EVERY Goodie Bag annual subscriber',
        'Active paid subscription to PostHog',
        `Organizations with a paid PostHog invoice before ${EVERY_CREDIT_ELIGIBILITY_CUTOFF} qualify only for credits toward PostHog's AI products`,
    ],
    footerNote: (
        <span className="text-xs">
            *Credits toward PostHog's AI products and PostHog core credits are separate. Both currently exclude PostHog
            Code and AI Gateway.
        </span>
    ),
}
