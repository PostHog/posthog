import { useValues } from 'kea'

import { KeyboardGardenBackground } from 'scenes/authentication/shared/KeyboardGardenBackground'
import { userLogic } from 'scenes/userLogic'

// TODO: build the paper-desk signup screens (email step, then password step); renders under the `auth-flow-variant` flag.
function Signup(): JSX.Element | null {
    const { user } = useValues(userLogic)

    return !user ? (
        <KeyboardGardenBackground>
            <div className="text-center">
                <h2>Create your account</h2>
                <p className="text-secondary">Paper-desk signup — coming soon.</p>
            </div>
        </KeyboardGardenBackground>
    ) : null
}

export { Signup as PaperDeskSignup }
