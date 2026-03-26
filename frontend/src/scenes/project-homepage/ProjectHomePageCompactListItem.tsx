import React from 'react'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

export type RecentItemRowProps = Pick<LemonButtonProps, 'onClick' | 'to'> & {
    title: string
    subtitle: React.ReactNode
    prefix?: React.ReactNode
    suffix?: React.ReactNode
    dataAttr?: string
}

export function ProjectHomePageCompactListItem({
    to,
    onClick,
    title,
    subtitle,
    prefix,
    suffix,
    dataAttr,
}: RecentItemRowProps): JSX.Element {
    return (
        <LemonButton
            fullWidth
            to={to}
            onClick={onClick}
            className="h-12"
            data-attr={dataAttr ? `insights-home-tab-${dataAttr}` : undefined}
        >
            <div className="flex items-start justify-between overflow-hidden gap-2 flex-1">
                {prefix ? <span className="flex shrink-0 text-secondary text-xl">{prefix}</span> : null}

                <div className="truncate flex flex-col gap-y-0.5 flex-1">
                    <div className="text-link truncate">{title}</div>
                    <div className="truncate text-secondary font-normal text-xs">{subtitle}</div>
                </div>

                {suffix ? <span className="shrink-0">{suffix}</span> : null}
            </div>
        </LemonButton>
    )
}
