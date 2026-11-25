import { IconQuestion } from '@posthog/icons'
import { Button, Heading, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { APPROVALS_TOOLTIP } from './emailPreferencesCopy'

export function QuillApprovalsHeading(): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Approvals
            </Heading>
            <Tooltip>
                <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About approval emails" />}>
                    <IconQuestion />
                </TooltipTrigger>
                <TooltipContent>{APPROVALS_TOOLTIP}</TooltipContent>
            </Tooltip>
        </div>
    )
}
