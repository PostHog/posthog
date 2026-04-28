import clsx from 'clsx'
import React from 'react'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

export type RecentItemRowProps = Pick<LemonButtonProps, 'onClick' | 'to'> & {
    title: string
    subtitle: React.ReactNode
    prefix?: React.ReactNode
    suffix?: React.ReactNode
    dataAttr?: string
    /** When true, text wraps instead of truncating and the row height grows to fit. */
    allowWrap?: boolean
}

export function ProjectHomePageCompactListItem({
    to,
    onClick,
    title,
    subtitle,
    prefix,
    suffix,
    dataAttr,
    allowWrap,
}: RecentItemRowProps): JSX.Element {
    return (
        <LemonButton
            fullWidth
            to={to}
            onClick={onClick}
            className={allowWrap ? 'h-auto' : 'h-12'}
            data-attr={dataAttr ? `insights-home-tab-${dataAttr}` : undefined}
        >
            <div className="flex items-start justify-between overflow-hidden gap-2 flex-1">
                {prefix ? <span className="flex shrink-0 text-secondary text-xl">{prefix}</span> : null}

                <div className={clsx('flex flex-col gap-y-0.5 flex-1', !allowWrap && 'truncate')}>
                    <div className={clsx('text-link', allowWrap ? 'break-words' : 'truncate')}>{title}</div>
                    <div className={clsx('text-secondary font-normal text-xs', !allowWrap && 'truncate')}>
                        {subtitle}
                    </div>
                </div>

                {suffix ? <span className="shrink-0">{suffix}</span> : null}
            </div>
        </LemonButton>
    )
}
