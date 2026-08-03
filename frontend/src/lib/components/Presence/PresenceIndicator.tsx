import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { type PresenceLogicProps, presenceLogic } from './presenceLogic'
import { presenceName } from './presenceUtils'

export interface PresenceIndicatorProps extends PresenceLogicProps {
    className?: string
}

/**
 * Shows who else is looking at the same object right now, so two people don't unknowingly work on
 * the same thing. Attach it to any scope + item_id pair that has presence enabled on the backend.
 */
export function PresenceIndicator({ className, ...logicProps }: PresenceIndicatorProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const flagEnabled = !!featureFlags[FEATURE_FLAGS.PRESENCE_INDICATOR]

    if (!flagEnabled) {
        return null
    }

    return <PresenceIndicatorContents className={className} {...logicProps} />
}

/** Split out so the flag check happens before `presenceLogic` mounts and starts heartbeating. */
function PresenceIndicatorContents({ className, ...logicProps }: PresenceIndicatorProps): JSX.Element | null {
    const { otherViewers, presenceLabel } = useValues(presenceLogic(logicProps))

    if (!otherViewers.length) {
        return null
    }

    return (
        <div className={className}>
            <div className="flex items-center gap-2">
                <ProfileBubbles
                    limit={4}
                    people={otherViewers.map((viewer) => ({
                        email: viewer.user.email,
                        name: viewer.user.first_name,
                        title:
                            viewer.activity === 'composing'
                                ? `${presenceName(viewer)} is replying`
                                : presenceName(viewer),
                    }))}
                />
                <span className="text-xs text-secondary">{presenceLabel}</span>
            </div>
        </div>
    )
}
