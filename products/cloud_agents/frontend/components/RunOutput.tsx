import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { CloudAgentRunResultApiOutput } from '../generated/api.schemas'

/** The structured result that the agent returned for the output schema of the run. */
export function RunOutput({ output }: { output: CloudAgentRunResultApiOutput }): JSX.Element {
    return (
        <div data-attr="cloud-agents-run-output">
            <div className="text-secondary text-xs">Output</div>
            <CodeSnippet language={Language.JSON} wrap thing="output">
                {JSON.stringify(output, null, 2)}
            </CodeSnippet>
        </div>
    )
}
