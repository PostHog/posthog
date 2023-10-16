import { SessionReplayFinalSteps } from '../shared-snippets'
import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'

export function ReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
