import { IconX } from '@posthog/icons'

import { Logo } from 'lib/brand/Logo'

import { CampaignConfig } from './types'

const EVERY_LOGO_BLACK = 'https://res.cloudinary.com/dmukukwp6/image/upload/every_black_d4ba0c3a4d.svg'
const EVERY_LOGO_WHITE = 'https://res.cloudinary.com/dmukukwp6/image/upload/every_white_438ee9fa45.svg'

const EveryHero: React.FC = () => {
    return (
        <div className="flex items-center justify-center gap-3 mb-4">
            <Logo style={{ height: '3rem' }} />
            <IconX className="size-8 opacity-60" />
            <img src={EVERY_LOGO_BLACK} alt="Every" className="h-8 w-auto [filter:brightness(0)] dark:hidden" />
            <img src={EVERY_LOGO_WHITE} alt="Every" className="hidden h-8 w-auto dark:block" />
        </div>
    )
}

export const everyCampaign: CampaignConfig = {
    name: 'Every Goodie Bag',
    heroTitle: '5x PostHog AI free allowance for 12 months',
    heroSubtitle: 'An exclusive PostHog offer for Every Goodie Bag annual subscribers',
    HeroImage: EveryHero,
    benefits: [
        {
            title: '5x PostHog AI allowance',
            description: 'Get 5x the standard monthly free allowance for PostHog AI after redeeming your code.',
        },
        {
            title: '$2K credits for eligible PostHog organizations',
            description: 'Organizations without previous paid invoices also receive $2K in PostHog credits.',
        },
        {
            title: '12-month access',
            description: 'Campaign benefits run for one year from the day you redeem your code.',
        },
    ],
    eligibilityCriteria: [
        'Active Every Goodie Bag annual subscriber',
        'Organization admin or owner in PostHog',
        'Active paid subscription to PostHog',
        'Existing paying organizations receive the PostHog AI benefit only',
    ],
    footerNote:
        'Credits and campaign plan benefits expire 12 months from redemption. The $2K credit grant applies only to eligible organizations without previous paid invoices.',
}
