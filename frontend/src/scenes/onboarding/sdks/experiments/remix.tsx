import { SDKKey } from '~/types'

import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallRemixJSInstructions } from '../sdk-install-instructions/remix'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsRemixInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRemixJSInstructions />
            <h3>Client-side rendering</h3>
            <ExperimentsImplementationSnippet sdkKey={SDKKey.JS_WEB} />
            <h3>Server-side rendering</h3>
            <h4>Install</h4>
            <NodeInstallSnippet />
            <h4>Configure</h4>
            <NodeSetupSnippet />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}
