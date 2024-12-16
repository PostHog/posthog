import { SDKKey } from '~/types'

import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsNuxtInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNuxtJSInstructions />
            <h3>Client-side rendering</h3>
            <ExperimentsImplementationSnippet sdkKey={SDKKey.REACT} />
            <h3>Server-side rendering</h3>
            <h4>Install</h4>
            <NodeInstallSnippet />
            <h4>Configure</h4>
            <NodeSetupSnippet />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.REACT} />
        </>
    )
}
