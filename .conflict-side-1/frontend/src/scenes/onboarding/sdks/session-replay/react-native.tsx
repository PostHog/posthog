import { SDKInstallRNInstructions } from '../sdk-install-instructions'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function RNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions includeReplay={true} />
            <SessionReplayFinalSteps />
        </>
    )
}
