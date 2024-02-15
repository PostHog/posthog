import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
