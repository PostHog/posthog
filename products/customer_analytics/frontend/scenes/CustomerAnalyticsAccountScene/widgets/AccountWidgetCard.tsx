import clsx from 'clsx'
import { ReactNode } from 'react'

import { LemonCard } from '@posthog/lemon-ui'

import { AccountWidgetHeader, AccountWidgetHeaderProps } from './AccountWidgetHeader'

export interface AccountWidgetCardProps extends Omit<AccountWidgetHeaderProps, 'className'> {
    wide?: boolean
    bodyClassName?: string
    children: ReactNode
}

export function AccountWidgetCard({
    wide,
    bodyClassName,
    children,
    ...headerProps
}: AccountWidgetCardProps): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className={clsx('p-0 overflow-hidden flex flex-col min-w-0', wide && '@2xl:col-span-2')}
            data-attr={headerProps['data-attr']}
        >
            <AccountWidgetHeader {...headerProps} data-attr={undefined} />
            <div className={bodyClassName ?? 'min-w-0'}>{children}</div>
        </LemonCard>
    )
}
