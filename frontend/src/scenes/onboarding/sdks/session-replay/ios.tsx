import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function iOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions includeReplay={true} />
            <SessionReplayFinalSteps />
        </>
    )
}
