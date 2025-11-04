import { IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'

export interface CampaignBenefit {
    title: string
    description: string
}

export interface CampaignConfig {
    name: string
    heroTitle: string
    heroSubtitle: string
    benefits: CampaignBenefit[]
    eligibilityCriteria: string[]
    footerNote?: string | JSX.Element
    HeroImage?: React.FC<any>
}

const LennyHero: React.FC = () => {
    return (
        <div className="flex items-center justify-center gap-3 mb-4">
            <Logo style={{ height: '3rem' }} />
            <IconX className="size-8 opacity-60" />
            <img
                src="https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/lenny_logo_4f52d3bb15.webp"
                alt="Lenny's Newsletter"
                className="h-12 w-12 rounded-lg"
            />
            <img
                src="https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/lenny_ca568a9fda.png"
                alt="Lenny's Newsletter"
                className="h-6"
            />
        </div>
    )
}

export const lennyCampaign: CampaignConfig = {
    name: "Lenny's Newsletter",
    heroTitle: 'Get FREE PostHog Scale for 12 months (worth $9,000)',
    heroSubtitle: "Redeem your offer for annual subscribers of Lenny's Newsletter",
    HeroImage: LennyHero,
    benefits: [
        {
            title: 'Priority support',
            description: 'Get help from our team with a 24-hour target response time',
        },
        {
            title: 'SAML SSO & advanced permissions',
            description:
                'Enterprise single sign-on with fine-grained access control, SSO enforcement, and 2FA requirements',
        },
        {
            title: 'Audit logs',
            description: 'Track all changes in your organization with 2 months of retention',
        },
        {
            title: 'Extended session replay retention',
            description: 'Keep your session replay data for up to 12 months instead of the standard 3',
        },
        {
            title: 'Managed reverse proxy',
            description: 'Up to 2 proxies to improve data collection and bypass ad blockers',
        },
    ],
    eligibilityCriteria: [
        "Active Lenny's Newsletter annual subscriber",
        'PostHog organization created after November 10, 2025',
        'Active paid subscription to PostHog',
    ],
    footerNote: (
        <>
            ... and{' '}
            <Link to="https://posthog.com/platform-packages" target="_blank">
                many more
            </Link>
            ! All features are available for 12 months from the date you redeem your coupon.
        </>
    ),
}
