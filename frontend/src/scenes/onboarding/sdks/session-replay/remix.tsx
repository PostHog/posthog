import { SDKInstallRemixJSInstructions } from '../sdk-install-instructions/remix'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function RemixInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRemixJSInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
