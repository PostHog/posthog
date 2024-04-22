import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'
import { SessionReplayFinalSteps } from '../shared-snippets'

export function NuxtJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNuxtJSInstructions />
            <SessionReplayFinalSteps />
        </>
    )
}
