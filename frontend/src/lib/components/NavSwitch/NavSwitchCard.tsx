import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AdvertisementCard, ProductHeroDisplay } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'

import { NAV_SWITCH_CARD_LOGIC_PROPS, OLD_NAV_SUNSET, navSwitchLogic } from './navSwitchLogic'

const NAV_SWITCH_CARD_HERO: ProductHeroDisplay = { accentColor: 'var(--color-accent)' }

/** Tells people on the old navigation when it goes away, and lets them switch. */
export function NavSwitchCard(): JSX.Element | null {
    const { switchAvailable, switchLabel } = useValues(navSwitchLogic)
    const { switchNav, showSwitchHint } = useActions(navSwitchLogic)
    const { hidden } = useValues(navPanelAdvertisementLogic(NAV_SWITCH_CARD_LOGIC_PROPS))
    const shouldShow = switchAvailable && !hidden

    useEffect(() => {
        if (shouldShow) {
            // pinned: analytics event name.
            posthog.capture('old nav sunset card shown')
        }
    }, [shouldShow])

    if (!shouldShow) {
        return null
    }

    return (
        <div className="w-full">
            <BindLogic logic={navPanelAdvertisementLogic} props={NAV_SWITCH_CARD_LOGIC_PROPS}>
                <AdvertisementCard
                    title="New design"
                    hero={NAV_SWITCH_CARD_HERO}
                    text={
                        <span className="flex flex-col items-start gap-2 pb-2">
                            <span>This version of our design is going away in {OLD_NAV_SUNSET}.</span>
                            <LemonButton
                                type="primary"
                                size="xsmall"
                                onClick={() => switchNav('navbar')}
                                data-attr="nav-switch-button"
                            >
                                {switchLabel}
                            </LemonButton>
                        </span>
                    }
                    onClose={() => {
                        // pinned: analytics event name.
                        posthog.capture('old nav sunset card dismissed')
                        // The card goes away for good, so point at where the switch stays.
                        showSwitchHint()
                    }}
                />
            </BindLogic>
        </div>
    )
}
