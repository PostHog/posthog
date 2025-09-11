import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function SvelteInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallSvelteJSInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
