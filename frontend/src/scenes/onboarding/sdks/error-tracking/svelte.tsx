import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'

export function SvelteInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallSvelteJSInstructions />
            <h3>Client-side rendering</h3>
            {/* What to do here */}
            <h3>Server-side rendering</h3>
            <h4>Install</h4>
            <NodeInstallSnippet />
            <h4>Configure</h4>
            <NodeSetupSnippet />
        </>
    )
}
