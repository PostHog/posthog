import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function FlutterInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFlutterInstructions includeReplay={true} requiresManualInstall={true} />
            <SessionReplayFinalSteps />
        </>
    )
}
