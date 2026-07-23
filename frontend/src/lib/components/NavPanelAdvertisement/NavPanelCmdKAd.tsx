import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'

import { AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export const CMD_K_AD_CAMPAIGN = 'cmd-k-discovery'

/** Dismissible callout advertising the Cmd+K command menu, the `footer-callout` variant of the Cmd+K nav experiment. */
export function NavPanelCmdKAd(): JSX.Element | null {
    const logicProps = { campaign: CMD_K_AD_CAMPAIGN }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)
    const { openCommand } = useActions(commandLogic)

    useEffect(() => {
        if (!hidden) {
            posthog.capture('nav panel campaign shown', { campaign: CMD_K_AD_CAMPAIGN })
        }
    }, [hidden])

    if (hidden) {
        return null
    }

    return (
        <div className="w-full">
            <Link
                className="text-primary"
                data-attr="nav-panel-cmd-k-ad"
                onClick={() => {
                    posthog.capture('nav search clicked')
                    openCommand('nav-panel-callout')
                }}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
                    <AdvertisementCard
                        emoji="🔍"
                        emojiLabel="magnifying glass"
                        title="Find anything faster"
                        text={
                            <>
                                Press <RenderKeybind keybind={[keyBinds.search]} /> to search everything in your
                                project: insights, dashboards, people, and more.
                            </>
                        }
                        onClose={() => {
                            posthog.capture('nav panel campaign dismissed', { campaign: CMD_K_AD_CAMPAIGN })
                        }}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
