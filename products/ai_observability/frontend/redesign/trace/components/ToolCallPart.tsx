import { IconWrench } from '@posthog/icons'

import { ToolCallValue } from './ToolCallValue'

export interface ToolCallPartProps {
    name: string
    args: unknown
    result?: unknown
    highlightQuery?: string | null
}

export function ToolCallPart({ name, args, result, highlightQuery = null }: ToolCallPartProps): JSX.Element {
    return (
        <div className="rounded border border-primary bg-surface-primary">
            <div className="flex items-center gap-1.5 border-b border-primary px-2 py-1 text-xs font-semibold">
                <IconWrench className="text-secondary" />
                <span className="font-mono">{name}</span>
            </div>
            <ToolCallValue value={args} highlightQuery={highlightQuery} />
            {result !== undefined && result !== null ? (
                <>
                    <div className="border-t border-primary px-2 py-1 text-xs font-semibold text-secondary">Result</div>
                    <ToolCallValue value={result} highlightQuery={highlightQuery} />
                </>
            ) : null}
        </div>
    )
}
