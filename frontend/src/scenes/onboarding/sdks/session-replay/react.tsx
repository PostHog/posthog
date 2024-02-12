import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function ReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
