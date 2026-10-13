import type { ComponentProps } from 'react'

import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

type TodayActionButtonProps = ComponentProps<typeof Button> & {
    disabledReason?: string | null
    tooltip?: string
}

export function TodayActionButton({
    disabledReason,
    tooltip,
    disabled,
    ...props
}: TodayActionButtonProps): JSX.Element {
    const label = disabledReason || tooltip
    const button = <Button {...props} disabled={disabled || !!disabledReason} />
    if (!label) {
        return button
    }
    return (
        <Tooltip>
            <TooltipTrigger render={button} delay={props.size?.startsWith('icon') ? 0 : undefined} />
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}
