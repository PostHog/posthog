import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

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
