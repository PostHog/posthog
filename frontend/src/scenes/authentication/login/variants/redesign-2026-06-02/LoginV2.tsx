import { BridgePage } from 'lib/components/BridgePage/BridgePage'

// TODO: build the redesign-2026-06-02 login; renders under the `auth-flow-variant` flag.
export function LoginV2(): JSX.Element {
    return (
        <BridgePage view="login" hedgehog message="Welcome back">
            <div className="deprecated-space-y-4">
                <h2>Log in</h2>
                <p className="text-secondary">Redesigned sign-in — coming soon.</p>
            </div>
        </BridgePage>
    )
}
