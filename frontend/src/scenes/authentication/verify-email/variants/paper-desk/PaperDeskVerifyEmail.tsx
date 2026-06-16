import { useValues } from 'kea'

import { KeyboardGardenBackground } from 'scenes/authentication/shared/KeyboardGardenBackground'

import { verifyEmailLogic } from '../../verifyEmailLogic'

// TODO: build the paper-desk email verification screens; renders under the `auth-flow-variant` flag.
// Screens to design: check inbox (view "pending"), success (view "success"), expired/invalid link (view "invalid").
function VerifyEmail(): JSX.Element {
    const { view } = useValues(verifyEmailLogic)

    let message = 'Check your inbox — paper-desk verification screen coming soon.'
    if (view === 'success') {
        message = 'Email verified — paper-desk success screen coming soon.'
    } else if (view === 'invalid') {
        message = 'That link is expired or invalid — paper-desk screen coming soon.'
    } else if (view === 'verify') {
        message = 'Verifying your email — paper-desk screen coming soon.'
    }

    return (
        <KeyboardGardenBackground>
            <div className="text-center">
                <h2>Verify your email</h2>
                <p className="text-secondary">{message}</p>
            </div>
        </KeyboardGardenBackground>
    )
}

export { VerifyEmail as PaperDeskVerifyEmail }
