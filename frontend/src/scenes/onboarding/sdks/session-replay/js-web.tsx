import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { SessionReplayFinalSteps } from '../shared-snippets'
import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <LemonDivider thick dashed className="my-4" />
            <h3>Final steps</h3>
            <SessionReplayFinalSteps />
        </>
    )
}
