import { useValues } from 'kea'

import { KeyboardGardenBackground } from 'scenes/authentication/shared/KeyboardGardenBackground'
import { userLogic } from 'scenes/userLogic'

import { inviteSignupLogic } from '../../inviteSignupLogic'

// TODO: build the paper-desk invited signup screens; renders under the `auth-flow-variant` flag.
// Screens to design: new user (no account), existing account (logged in), invalid link (error).
export function PaperDeskInviteSignup(): JSX.Element {
    const { invite, error } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    let message = 'Create your account — paper-desk invited signup coming soon.'
    if (error) {
        message = 'Invalid or expired invite — paper-desk screen coming soon.'
    } else if (invite && user) {
        message = 'Accept invite with your existing account — paper-desk screen coming soon.'
    }

    return (
        <KeyboardGardenBackground>
            <div className="text-center">
                <h2>You're invited</h2>
                <p className="text-secondary">{message}</p>
            </div>
        </KeyboardGardenBackground>
    )
}
