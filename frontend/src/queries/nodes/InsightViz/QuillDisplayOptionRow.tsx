import { ReactNode } from 'react'

import { Field, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillDisplayOptionRow({
    disabledReason,
    children,
}: {
    disabledReason?: string | null
    children: ReactNode
}): JSX.Element {
    if (!disabledReason) {
        return <Field orientation="horizontal">{children}</Field>
    }

    // A disabled control takes no pointer events, so the reason hangs off the whole row.
    return (
        <Tooltip>
            <TooltipTrigger render={<Field orientation="horizontal" data-disabled />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-64">{disabledReason}</TooltipContent>
        </Tooltip>
    )
}
