import { SDKKey } from '~/types'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'

export function FeatureFlagsNextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
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
