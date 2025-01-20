import { LemonDivider } from '@posthog/lemon-ui'

import { SDKKey } from '~/types'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.IOS} />
        </>
    )
}
