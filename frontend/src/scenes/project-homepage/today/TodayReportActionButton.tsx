import { ReactNode } from 'react'

import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

interface TodayReportActionButtonProps {
    children: ReactNode
    dataAttr: string
    variant?: 'primary' | 'outline'
    to?: string
    targetBlank?: boolean
    onClick?: () => void
    disabledReason?: string
}

/** An action on the report page. A disabled action keeps focus and shows its reason in a tooltip. */
export function TodayReportActionButton({
    children,
    dataAttr,
    variant = 'outline',
    to,
    targetBlank = false,
    onClick,
    disabledReason,
}: TodayReportActionButtonProps): JSX.Element {
    const link = to && !disabledReason ? to : undefined

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        variant={variant}
                        disabled={!!disabledReason}
                        nativeButton={!link}
                        render={
                            link ? <LinkPrimitive to={link} target={targetBlank ? '_blank' : undefined} /> : undefined
                        }
                        onClick={link ? undefined : onClick}
                        data-attr={dataAttr}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            {disabledReason && <TooltipContent>{disabledReason}</TooltipContent>}
        </Tooltip>
    )
}
