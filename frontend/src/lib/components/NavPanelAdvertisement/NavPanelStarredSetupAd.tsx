import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import * as star from '@posthog/brand/hoggies/png/star'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { navProductsTabLogic } from '~/layout/panel-layout/navbar/tabs/navProductsTabLogic'

import { AdvertisementCard, NAV_PANEL_CARD_TYPE, ProductPushDisplay } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

const logicProps = { dismissKey: 'starred-products-setup' }

const STARRED_SETUP_HERO: ProductPushDisplay = {
    Hoggie: pngHoggie(star),
    accentColor: 'var(--color-accent)',
    tagline: '',
    hoggieOffset: { x: 58 },
}

export function NavPanelStarredSetupAd(): JSX.Element | null {
    const { hidden } = useValues(navPanelAdvertisementLogic(logicProps))
    const { openStarredSetup, dismissStarredSetup } = useActions(navProductsTabLogic)

    useEffect(() => {
        if (!hidden) {
            posthog.capture('nav panel starred setup shown', { card_type: NAV_PANEL_CARD_TYPE.STARRED_SETUP })
        }
    }, [hidden])

    if (hidden) {
        return null
    }

    return (
        <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
            <AdvertisementCard
                title="A simpler sidebar"
                hero={STARRED_SETUP_HERO}
                text={
                    <span className="flex flex-col items-start gap-2">
                        <span>
                            Many of you told us things were too hard to find, so we rebuilt the sidebar around the
                            products you pick.
                        </span>
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            onClick={() => {
                                posthog.capture('nav panel starred setup clicked', {
                                    card_type: NAV_PANEL_CARD_TYPE.STARRED_SETUP,
                                })
                                openStarredSetup()
                            }}
                            data-attr="nav-panel-starred-setup-open"
                        >
                            Choose starred products
                        </LemonButton>
                    </span>
                }
                onClose={() => {
                    posthog.capture('nav panel starred setup dismissed', {
                        card_type: NAV_PANEL_CARD_TYPE.STARRED_SETUP,
                    })
                    dismissStarredSetup()
                }}
            />
        </BindLogic>
    )
}
