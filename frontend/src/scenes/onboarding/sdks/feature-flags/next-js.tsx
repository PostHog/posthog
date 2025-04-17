import { SDKKey } from '~/types'

import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsNextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions hideWizard />
            <h3>Client-side rendering</h3>
            <FlagImplementationSnippet sdkKey={SDKKey.REACT} />
            <h3>Server-side rendering</h3>
            <h4>Install</h4>
            <NodeInstallSnippet />
            <h4>Configure</h4>
            <NodeSetupSnippet />
            <FlagImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}
