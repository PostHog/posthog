import { SDKKey } from '~/types'

import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsSvelteInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallSvelteJSInstructions hideWizard />
            <h3>Client-side rendering</h3>
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
            <h3>Server-side rendering</h3>
            <h4>Install</h4>
            <NodeInstallSnippet />
            <h4>Configure</h4>
            <NodeSetupSnippet />
            <FlagImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}
