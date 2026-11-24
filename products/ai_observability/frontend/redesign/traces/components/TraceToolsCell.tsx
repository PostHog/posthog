import { LemonTag } from '@posthog/lemon-ui'

const SHOWN_TOOLS = 3

export interface TraceToolsCellProps {
    tools: string[]
}

export function TraceToolsCell({ tools }: TraceToolsCellProps): JSX.Element | null {
    if (tools.length === 0) {
        return null
    }
    const hiddenTools = tools.slice(SHOWN_TOOLS)
    return (
        <div className="flex items-center gap-1">
            {tools.slice(0, SHOWN_TOOLS).map((tool) => (
                <LemonTag key={tool} type="muted" size="small" title={tool} className="max-w-32 shrink-0">
                    <span className="truncate">{tool}</span>
                </LemonTag>
            ))}
            {hiddenTools.length > 0 ? (
                <span title={hiddenTools.join(', ')} className="shrink-0 text-xs text-secondary">
                    +{hiddenTools.length}
                </span>
            ) : null}
        </div>
    )
}
