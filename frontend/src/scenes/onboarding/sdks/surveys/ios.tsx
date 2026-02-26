import type { JSX } from 'react'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'

export function iOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions includeSurveys={true} includeExperimentalSpi={false} />
        </>
    )
}
