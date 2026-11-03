import clsx from 'clsx'
import { ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function RecordingRowStat({
    icon,
    value,
    label,
    destructive = false,
}: {
    icon: ReactNode
    value: ReactNode
    label: string
    destructive?: boolean
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        className={clsx(
                            'flex items-center gap-x-0.5 shrink-0',
                            destructive && 'text-destructive-foreground'
                        )}
                    />
                }
            >
                {icon}
                {value}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}
