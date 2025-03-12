import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { cn } from 'lib/utils/css-classes'

export function PerformanceEventLabel({
    label,
    name,
    expanded,
}: {
    expanded: boolean
    name: string | undefined
    label?: string | undefined
}): JSX.Element {
    return (
        <span className={cn('flex-1 overflow-hidden', !expanded && 'truncate')}>
            {label}
            {expanded ? (
                <CodeSnippet language={Language.Markup} wrap thing="performance event name">
                    {name}
                </CodeSnippet>
            ) : (
                name
            )}
        </span>
    )
}
