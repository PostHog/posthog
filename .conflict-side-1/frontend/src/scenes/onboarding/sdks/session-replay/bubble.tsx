import { SDKInstallBubbleInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function BubbleInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallBubbleInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
