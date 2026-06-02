import { useValues } from 'kea'

import { KeyboardGardenBackground } from 'scenes/authentication/shared/KeyboardGardenBackground'
import { userLogic } from 'scenes/userLogic'

// TODO: build the redesign-2026-06-02 signup; renders under the `auth-flow-variant` flag.
export function SignupV2(): JSX.Element | null {
    const { user } = useValues(userLogic)

    return !user ? (
        <KeyboardGardenBackground>
            <div className="text-center">
                <h2>Create your account</h2>
                <p className="text-secondary">Redesigned signup — coming soon.</p>
            </div>
        </KeyboardGardenBackground>
    ) : null
}
