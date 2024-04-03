import { SDKInstallFramerInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function FramerInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFramerInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
