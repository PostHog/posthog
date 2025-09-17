import clsx from 'clsx'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

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
        <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
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
