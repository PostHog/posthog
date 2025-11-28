import { IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'

import { CampaignConfig } from './types'

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
    heroSubtitle: "We like Lenny's Newsletter so much we made this exclusive off for annual subscribers",
    HeroImage: LennyHero,
    benefits: [
        {
            title: 'Priority support',
            description: "Get help from our team. You'll speak to an actual engineer too!",
        },
        {
            title: 'SAML, SSO & advanced permissions',
            description: 'Fine-grained access control, SSO enforcement, and 2FA requirements',
        },
        {
            title: 'Audit logs',
            description: '2 months of retention so you can track changes in your organization',
        },
        {
            title: 'Extended session replay retention',
            description: 'Keep your session replay data for 12 months instead of the standard 3',
        },
        {
            title: 'Managed reverse proxy',
            description: 'Up to 2 proxies to improve data collection and bypass ad blockers',
        },
    ],
    eligibilityCriteria: [
        "Active Lenny's Newsletter annual subscriber",
        'PostHog organization created after December 2, 2025',
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
