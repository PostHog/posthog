import { SDKInstallVueInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function VueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
