import { IconWrench } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { toDisplayText } from './jsonText'

export interface ToolCallPartProps {
    name: string
    args: unknown
    result?: unknown
    isError?: boolean
}

export function ToolCallPart({ name, args, result, isError }: ToolCallPartProps): JSX.Element {
    return (
        <div className="rounded border border-primary bg-surface-primary">
            <div className="flex items-center gap-1.5 border-b border-primary px-2 py-1 text-xs font-semibold">
                <IconWrench className="text-secondary" />
                <span className="font-mono">{name}</span>
                {isError ? (
                    <LemonTag type="danger" size="small">
                        Error
                    </LemonTag>
                ) : null}
            </div>
            <pre className="m-0 max-h-60 overflow-auto px-2 py-1 text-xs">{toDisplayText(args)}</pre>
            {result !== undefined ? (
                <>
                    <div className="border-t border-primary px-2 py-1 text-xs font-semibold text-secondary">Result</div>
                    <pre className="m-0 max-h-60 overflow-auto px-2 py-1 text-xs">{toDisplayText(result)}</pre>
                </>
            ) : null}
        </div>
    )
}
