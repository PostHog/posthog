import { SDKInstallAstroInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function AstroInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAstroInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
