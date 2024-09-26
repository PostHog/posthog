import React from 'react'

import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'

export function AndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions includeReplay={true} />
        </>
    )
}
