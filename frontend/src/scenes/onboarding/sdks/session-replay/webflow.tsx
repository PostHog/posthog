import { SDKInstallWebflowInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function WebflowInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallWebflowInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
