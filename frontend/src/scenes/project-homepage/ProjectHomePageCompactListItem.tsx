import React from 'react'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

export type RecentItemRowProps = Pick<LemonButtonProps, 'onClick' | 'to'> & {
    title: string
    subtitle: React.ReactNode
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
        <LemonButton fullWidth to={to} onClick={onClick} className="h-12">
            <div className="flex flex-1 items-start justify-between gap-2 overflow-hidden">
                {prefix ? <span className="text-secondary flex shrink-0 text-xl">{prefix}</span> : null}

                <div className="flex flex-1 flex-col gap-y-0.5 truncate">
                    <div className="text-link truncate">{title}</div>
                    <div className="text-secondary truncate text-xs font-normal">{subtitle}</div>
                </div>

                {suffix ? <span className="shrink-0">{suffix}</span> : null}
            </div>
        </LemonButton>
    )
}
