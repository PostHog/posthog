import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { miniFiltersLogic } from '../miniFiltersLogic'

export function PerformanceEventLabel({
    label,
    name,
    expanded,
}: {
    expanded: boolean
    name: string | undefined
    label?: string | undefined
}): JSX.Element {
    const { showLineTooltips } = useValues(miniFiltersLogic)

    if (expanded) {
        return (
            <span className="flex-1 overflow-hidden">
                {label}
                <CodeSnippet language={Language.Markup} wrap thing="performance event name">
                    {name}
                </CodeSnippet>
            </span>
        )
    }

    if (!name) {
        return <span className="flex-1 overflow-hidden truncate">{label}</span>
    }

    return (
        <Tooltip title={showLineTooltips ? name : undefined}>
            <span className="flex-1 overflow-hidden truncate">
                {label}
                {name}
            </span>
        </Tooltip>
    )
}
