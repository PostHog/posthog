import { ReactNode } from 'react'

import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

interface TodayRailButtonProps {
    label: string
    current?: boolean
    onClick: () => void
    dataAttr: string
    children: ReactNode
}

/** An icon-only rail control. The label is its accessible name and its tooltip. */
export function TodayRailButton({
    label,
    current = false,
    onClick,
    dataAttr,
    children,
}: TodayRailButtonProps): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-lg"
                        aria-label={label}
                        aria-current={current ? 'page' : undefined}
                        data-attr={dataAttr}
                        onClick={onClick}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
    )
}
