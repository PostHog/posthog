import { SDKKey } from '~/types'

import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsNextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions hideWizard />
            <h3>Client-side rendering</h3>
            <ExperimentsImplementationSnippet sdkKey={SDKKey.REACT} />
            <h3>Server-side rendering</h3>
            <h4>Install</h4>
            <NodeInstallSnippet />
            <h4>Configure</h4>
            <NodeSetupSnippet />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}
