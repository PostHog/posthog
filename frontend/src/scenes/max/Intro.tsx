import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconX } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { maxLogic } from './maxLogic'

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { headline, description } = useValues(maxLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Check if user previously had floating Max and hasn't yet closed the rollback banner
    const shouldShowRollbackBanner =
        featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG] &&
        !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG_ACKED]

    return (
        <>
            {shouldShowRollbackBanner && (
                <div className="mb-4 w-full max-w-160 px-3">
                    <LemonBanner
                        type="info"
                        dismissKey={FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG_ACKED}
                        onClose={() =>
                            // Person properties-based flag allows for cross-device dismiss
                            posthog.setPersonPropertiesForFlags(
                                { [FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG_ACKED]: true },
                                true
                            )
                        }
                        className="text-sm text-pretty"
                    >
                        <strong>Thanks for trying out Floating Max!</strong> Based on data and feedback, we're moving
                        Max back to the sidebar. Click <IconX /> to forget Max was ever able to float.
                    </LemonBanner>
                </div>
            )}
            <div className="flex">
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
                            // Make the hedeghog face left, which looks better in the side panel
                            actor.direction = 'left'
                        }, 100)
                    }
                />
            </div>
            <div className="text-center mb-1">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-sm text-secondary text-pretty">{description}</div>
            </div>
        </>
    )
}
