import { LemonTag } from '@posthog/lemon-ui'

import type { AggregatedToolCall } from './llmPlaygroundRunLogic'

function formatArguments(args: string): string {
    try {
        return JSON.stringify(JSON.parse(args), null, 2)
    } catch {
        // Streamed arguments can be a partial JSON string until the chunks finish.
        return args
    }
}

/** Read-only card for a tool call the model issued, shown in the result panel. */
export function ToolCallDisplay({ toolCall }: { toolCall: AggregatedToolCall }): JSX.Element {
    return (
        <div className="border rounded p-2 bg-surface-primary">
            <div className="flex items-center gap-2 mb-1">
                <LemonTag type="default" size="small">
                    Tool call
                </LemonTag>
                <span className="font-mono text-xs font-semibold">{toolCall.name || '…'}</span>
                <span className="font-mono text-xs text-muted truncate">{toolCall.id}</span>
            </div>
            <pre className="text-xs whitespace-pre-wrap break-words m-0 font-mono">
                {formatArguments(toolCall.arguments)}
            </pre>
        </div>
    )
}
