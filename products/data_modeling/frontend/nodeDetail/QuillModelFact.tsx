import type { ReactNode } from 'react'

import { Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillModelFact({
    label,
    hint,
    children,
}: {
    label: string
    hint?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <Text size="xs" variant="muted" render={<dt />} className="m-0">
                {hint ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={<span tabIndex={0} className="cursor-help border-b border-dashed border-border" />}
                        >
                            {label}
                        </TooltipTrigger>
                        <TooltipContent className="max-w-80">{hint}</TooltipContent>
                    </Tooltip>
                ) : (
                    label
                )}
            </Text>
            <Text size="xs" render={<dd />} className="m-0 min-w-0">
                {children}
            </Text>
        </div>
    )
}
