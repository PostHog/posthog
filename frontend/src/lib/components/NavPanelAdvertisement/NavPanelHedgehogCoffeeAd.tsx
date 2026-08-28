import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import * as coffeeRun from '@posthog/brand/hoggies/png/coffee-run'
import * as money from '@posthog/brand/hoggies/png/money'
import { Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { AdHeroDisplay, AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import {
    HERTS_WILDLIFE_TRUST_DONATE_URL,
    donationCampaignKey,
    navPanelHedgehogCoffeeLogic,
} from './navPanelHedgehogCoffeeLogic'

const HedgehogCoffeeRun = pngHoggie(coffeeRun)
const HedgehogMoney = pngHoggie(money)

// The whole card is a link to the donation page, so the Trust can only be named in plain text here -
// an inline link would nest one <a> inside another.
export const DONATION_VARIANTS: { hero: AdHeroDisplay; title: string; text: string }[] = [
    {
        hero: { Hoggie: HedgehogCoffeeRun, accentColor: 'var(--color-accent)' },
        title: 'Buy a hog a coffee',
        text: "PostHog's been free for you for a while. If it's been useful, chip in for the real hedgehogs at the Herts & Middlesex Wildlife Trust.",
    },
    {
        hero: { Hoggie: HedgehogMoney, accentColor: 'var(--color-accent)' },
        title: "We don't need the money",
        text: "But the Herts & Middlesex Wildlife Trust does. They look after actual hedgehogs, and you've been enjoying ours for free.",
    },
]

/**
 * Asks long-term free-tier orgs to donate to the hedgehog charity we support. Shows at most twice a
 * year: dismissal is persisted against the org's current six-month donation window, so closing the
 * card keeps it away until the next one.
 */
export function NavPanelHedgehogCoffeeAd({
    orgId,
    windowIndex,
}: {
    orgId: string
    windowIndex: number
}): JSX.Element | null {
    const campaign = donationCampaignKey(orgId, windowIndex)
    const logicProps = { campaign }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)
    const { isEligible } = useValues(navPanelHedgehogCoffeeLogic)

    // Windows start at 1, so the first ask is always the coffee card and the second alternates away.
    const variant = DONATION_VARIANTS[(windowIndex - 1) % DONATION_VARIANTS.length]
    const shown = !hidden && isEligible

    useEffect(() => {
        if (shown) {
            posthog.capture('nav panel campaign shown', { campaign })
        }
    }, [campaign, shown])

    if (!shown) {
        return null
    }

    return (
        <div className="w-full">
            <Link
                to={HERTS_WILDLIFE_TRUST_DONATE_URL}
                target="_blank"
                className="text-primary"
                data-attr="nav-panel-hedgehog-coffee-ad"
                onClick={() => {
                    posthog.capture('hedgehog coffee donation clicked', { campaign })
                }}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
                    <AdvertisementCard
                        title={variant.title}
                        text={variant.text}
                        hero={variant.hero}
                        onClose={() => {
                            posthog.capture('nav panel campaign dismissed', { campaign })
                        }}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
