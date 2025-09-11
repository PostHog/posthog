import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function AndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions includeReplay={true} />
            <SessionReplayFinalSteps />
        </>
    )
}
