import { ReactNode } from 'react'

import { Badge, Collapsible, CollapsibleContent, CollapsibleTrigger } from '@posthog/quill'

interface QuillAlertAdvancedOptionsProps {
    children: ReactNode
    enabledCount?: number
    defaultOpen?: boolean
}

export function QuillAlertAdvancedOptions({
    children,
    enabledCount = 0,
    defaultOpen = false,
}: QuillAlertAdvancedOptionsProps): JSX.Element {
    const countLabel = `${enabledCount} advanced option${enabledCount === 1 ? '' : 's'} on`

    return (
        <Collapsible defaultOpen={defaultOpen} className="rounded-md border border-border p-2">
            <CollapsibleTrigger>
                <span className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="min-w-0">Advanced options</span>
                    {enabledCount > 0 ? (
                        <Badge variant="info" aria-label={countLabel}>
                            {enabledCount}
                        </Badge>
                    ) : null}
                </span>
            </CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-4 p-2">{children}</CollapsibleContent>
        </Collapsible>
    )
}
