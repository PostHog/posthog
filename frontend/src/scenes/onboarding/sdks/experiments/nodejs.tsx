import { LemonDivider } from '@posthog/lemon-ui'

import { SDKKey } from '~/types'

import { SDKInstallNodeInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsNodeJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNodeInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}
