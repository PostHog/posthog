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
    heroTitle: '$2K in AI credits + $2K in core credits',
    heroSubtitle: 'PostHog makes your product self-driving by turning context into code improvements.',
    HeroImage: EveryHero,
    benefits: [
        {
            title: '$2K AI credits',
            description: (
                <>
                    All eligible EVERY Goodie Bag customers receive $2K in AI credits. Today, those credits cover:
                    <ul className="mt-1 ml-4 list-disc text-muted text-sm">
                        <li>PostHog AI (including the Slack agent)</li>
                        <li>Inbox (self-driving PRs based on your data)</li>
                    </ul>
                </>
            ),
        },
        {
            title: 'Early access to new AI features',
            description: 'Get access to select new AI features as they become available.',
        },
        {
            title: '$2K core credits*',
            description: `New PostHog customers are also eligible for $2K in credits for PostHog core tools, such as product analytics, session replay, error tracking, LLM observability, and data warehouse.`,
        },
        {
            title: '12-month access',
            description: 'Campaign benefits run for one year from the day you redeem your code.',
        },
    ],
    eligibilityCriteria: [
        'Active EVERY Goodie Bag annual subscriber',
        'Active paid subscription to PostHog',
        `Organizations with a non-$0 PostHog invoice before ${EVERY_CREDIT_ELIGIBILITY_CUTOFF} qualify only for AI credits`,
    ],
    footerNote: (
        <span className="text-xs">
            *AI credits and core credits are separate. Both currently exclude PostHog Code and AI Gateway.
        </span>
    ),
}
