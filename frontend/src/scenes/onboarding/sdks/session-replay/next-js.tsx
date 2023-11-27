import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
