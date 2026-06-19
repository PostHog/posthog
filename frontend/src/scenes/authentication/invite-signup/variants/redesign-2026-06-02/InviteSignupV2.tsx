import { BridgePage } from 'lib/components/BridgePage/BridgePage'

// TODO: build the redesign-2026-06-02 invited signup; renders under the `auth-flow-variant` flag.
export function InviteSignupV2(): JSX.Element {
    return (
        <BridgePage view="invites-signup" hedgehog message="You're invited">
            <div className="deprecated-space-y-4">
                <h2>Create your account</h2>
                <p className="text-secondary">Redesigned invited signup — coming soon.</p>
            </div>
        </BridgePage>
    )
}
