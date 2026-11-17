import { type ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, Heading, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillSectionHeading({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Heading size="sm" render={<h3 className="m-0" />}>
            {children}
        </Heading>
    )
}

export function QuillHelpTooltip({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={`About ${label}`} />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{help}</TooltipContent>
        </Tooltip>
    )
}
