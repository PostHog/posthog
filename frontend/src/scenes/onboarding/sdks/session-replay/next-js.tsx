import { SessionReplayFinalSteps } from '../shared-snippets'
import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
