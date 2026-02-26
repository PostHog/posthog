import type { JSX } from 'react'

import { SDKInstallVueInstructions } from '../sdk-install-instructions/vue'

export function VueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
        </>
    )
}
