import { useValues } from 'kea'
import { useState } from 'react'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'

import { authLogic } from '../authLogic'

export function JoinOrganizationHint(): JSX.Element | null {
    const { entry, step } = useValues(authLogic)
    const { preflight } = useValues(preflightLogic)
    const [showJoinOrg, setShowJoinOrg] = useState(false)

    if (step !== 'email' || entry !== 'signup' || preflight?.demo) {
        return null
    }
    return (
        <div className="mt-4 text-center">
            <button
                type="button"
                data-attr="signup-join-existing-org"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary text-xs"
                onClick={() => setShowJoinOrg((v) => !v)}
            >
                Trying to join an existing organization?
            </button>
            {showJoinOrg && (
                <AuthBanner variant="note" className="mt-3">
                    You'll need your invite link. When a teammate invites you, we email you a personal link. Didn't get
                    one? Check spam, or ask them to resend it from their members settings.
                </AuthBanner>
            )}
        </div>
    )
}
