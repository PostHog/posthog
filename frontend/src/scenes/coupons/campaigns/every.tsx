import { IconX } from '@posthog/icons'

import { Logo } from 'lib/brand'

import { CampaignConfig } from './types'

const EVERY_LOGO_BLACK = 'https://res.cloudinary.com/dmukukwp6/image/upload/every_black_d4ba0c3a4d.svg'
const EVERY_LOGO_WHITE = 'https://res.cloudinary.com/dmukukwp6/image/upload/every_white_438ee9fa45.svg'
// TODO: Keep this date in sync with EveryGoodieBagStrategy.INVOICE_CUTOFF_DATE in billing.
const EVERY_CREDIT_ELIGIBILITY_CUTOFF = 'July 14, 2026'

const EveryHero: React.FC = () => {
    return (
        <div className="flex items-center justify-center gap-3 mb-4">
            <Logo size="xl" />
            <IconX className="size-8 opacity-60" />
            <img src={EVERY_LOGO_BLACK} alt="EVERY" className="h-8 w-auto [filter:brightness(0)] dark:hidden" />
            <img src={EVERY_LOGO_WHITE} alt="EVERY" className="hidden h-8 w-auto dark:block" />
        </div>
    )
}

export const everyCampaign: CampaignConfig = {
    name: 'EVERY Goodie Bag',
    heroTitle: '$2K in AI credits + $2K in core credits',
    heroSubtitle: '$2K in AI credits for everyone, plus $2K in core credits for new PostHog customers.',
    HeroImage: EveryHero,
    benefits: [
        {
            title: "$2K credits toward PostHog's AI tools",
            description: (
                <>
                    All eligible EVERY Goodie Bag customers receive $2K in credits toward PostHog's AI tools. Today,
                    that includes:
                    <ul className="mt-1 ml-4 list-disc text-muted text-sm">
                        <li>PostHog AI (including the Slack agent)</li>
                        <li>Inbox (self-driving PRs based on your data)</li>
                    </ul>
                </>
            ),
        },
        {
            title: "Early access to new features in PostHog's AI tools",
            description: 'Get access to select new PostHog AI tools and features as they become available.',
        },
        {
            title: '$2K core credits',
            description: `Organizations with no non-$0 PostHog invoices before ${EVERY_CREDIT_ELIGIBILITY_CUTOFF} are also eligible for $2K in credits for PostHog core tools, such as product analytics, session replay, error tracking, AI observability, and data warehouse.`,
        },
        {
            title: '12-month access',
            description: 'Campaign benefits run for one year from the day you redeem your code.',
        },
    ],
    eligibilityCriteria: [
        'Active EVERY Goodie Bag annual subscriber',
        'Active paid subscription to PostHog',
        `No non-$0 PostHog invoices before ${EVERY_CREDIT_ELIGIBILITY_CUTOFF} to qualify for PostHog core credits`,
        'PostHog Code and AI Gateway are currently excluded from this offer',
    ],
}
