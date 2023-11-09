import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import React from 'react'

export type RecentItemRowProps = Pick<LemonButtonProps, 'onClick' | 'to'> & {
    title: string
    subtitle: string
    prefix?: React.ReactNode
    suffix?: React.ReactNode
}

export function ProjectHomePageCompactListItem({
    to,
    onClick,
    title,
    subtitle,
    prefix,
    suffix,
}: RecentItemRowProps): JSX.Element {
    return (
        <LemonButton fullWidth to={to} onClick={onClick}>
            <div className="flex items-center justify-between h-10 overflow-hidden gap-2 flex-1">
                {prefix ? <span className="shrink-0">{prefix}</span> : null}

                <div className="truncate space-y-1 flex-1">
                    <div className="text-link font-semibold truncate">{title}</div>
                    <div className="truncate text-default font-normal">{subtitle}</div>
                </div>

                {suffix ? <span className="shrink-0">{suffix}</span> : null}
            </div>
        </LemonButton>
    )
}
