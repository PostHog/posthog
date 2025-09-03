import { useActions, useValues } from 'kea'

import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { floatingMaxPositionLogic } from './floatingMaxPositionLogic'

export function FloatingMaxButton(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { position } = useValues(floatingMaxPositionLogic)

    // Only show floating button for users with FLOATING_ARTIFICIAL_HOG flag who haven't dismissed it
    const shouldShowFloatingButton =
        featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG] &&
        !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG_ACKED]

    if (!shouldShowFloatingButton) {
        return null
    }

    const handleClick = (): void => {
        openSidePanel(SidePanelTab.Max)
    }

    return (
        <div
            className={`fixed bottom-2 z-[var(--z-hedgehog-buddy)] cursor-pointer ${
                position.side === 'left' ? 'left-2' : 'right-2'
            }`}
            onClick={handleClick}
        >
            <div className="rounded-full border backdrop-blur-sm bg-[var(--glass-bg-3000)] p-1 hover:scale-105 transition-transform">
                <HedgehogBuddy
                    static
                    hedgehogConfig={{
                        ...hedgehogConfig,
                        walking_enabled: false,
                        controls_enabled: false,
                    }}
                    onClick={(actor) => {
                        if (Math.random() < 0.01) {
                            actor.setOnFire()
                        } else {
                            actor.setRandomAnimation(['stop'])
                        }
                    }}
                    onActorLoaded={(actor) =>
                        setTimeout(() => {
                            actor.setAnimation('wave')
                            // Face the appropriate direction based on position
                            actor.direction = position.side === 'left' ? 'right' : 'left'
                        }, 100)
                    }
                />
            </div>
        </div>
    )
}
