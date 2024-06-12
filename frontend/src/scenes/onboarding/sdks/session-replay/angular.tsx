import { SDKInstallAngularInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function AngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
