import { KeyboardGardenBackground } from 'scenes/authentication/shared/KeyboardGardenBackground'

// TODO: build the redesign-2026-06-02 invited signup; renders under the `auth-flow-variant` flag.
export function InviteSignupV2(): JSX.Element {
    return (
        <KeyboardGardenBackground>
            <div className="text-center">
                <h2>Create your account</h2>
                <p className="text-secondary">Redesigned invited signup — coming soon.</p>
            </div>
        </KeyboardGardenBackground>
    )
}
