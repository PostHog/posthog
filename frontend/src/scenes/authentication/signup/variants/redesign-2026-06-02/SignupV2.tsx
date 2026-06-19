import { useValues } from 'kea'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { userLogic } from 'scenes/userLogic'

// TODO: build the redesign-2026-06-02 signup; renders under the `auth-flow-variant` flag.
export function SignupV2(): JSX.Element | null {
    const { user } = useValues(userLogic)

    return !user ? (
        <BridgePage view="signup" sideLogo>
            <div className="deprecated-space-y-4">
                <h2>Create your account</h2>
                <p className="text-secondary">Redesigned signup — coming soon.</p>
            </div>
        </BridgePage>
    ) : null
}
