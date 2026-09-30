import { IconWrench } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { isPlainObject, toDisplayText } from './jsonText'
import { KeyValueTable } from './KeyValueTable'

export interface ToolCallPartProps {
    name: string
    args: unknown
    result?: unknown
    isError?: boolean
}

function ToolCallValue({ value }: { value: unknown }): JSX.Element {
    return (
        <div className="max-h-60 overflow-auto px-2 py-1">
            {isPlainObject(value) && Object.keys(value).length > 0 ? (
                <KeyValueTable entries={Object.entries(value)} className="gap-x-4 gap-y-1 font-mono text-xs" />
            ) : (
                <pre className="m-0 text-xs">{toDisplayText(value)}</pre>
            )}
        </div>
    )
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
            <ToolCallValue value={args} />
            {result !== undefined ? (
                <>
                    <div className="border-t border-primary px-2 py-1 text-xs font-semibold text-secondary">Result</div>
                    <ToolCallValue value={result} />
                </>
            ) : null}
        </div>
    )
}
