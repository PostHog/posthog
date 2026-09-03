import type { MouseEventHandler } from 'react'

import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { urls } from 'scenes/urls'

import { AccountLogo } from './AccountLogo'

export interface AccountNameCellProps {
    accountId?: string
    name: string
    externalId?: string | null
    logoDomain?: string | null
    onClick?: MouseEventHandler<HTMLElement>
    target?: '_blank'
}

export function AccountNameCell({
    accountId,
    name,
    externalId,
    logoDomain,
    onClick,
    target,
}: AccountNameCellProps): JSX.Element {
    return (
        <div className="flex items-center gap-2 min-w-40" data-account-id={accountId}>
            {logoDomain !== undefined ? <AccountLogo domain={logoDomain} name={name} /> : null}
            <div className="flex flex-col min-w-0">
                {accountId ? (
                    <Link
                        to={urls.customerAnalyticsAccount(accountId)}
                        className="font-semibold"
                        onClick={onClick}
                        target={target}
                    >
                        {name}
                    </Link>
                ) : (
                    <span className="font-semibold">{name}</span>
                )}
                {externalId ? (
                    <CopyToClipboardInline
                        explicitValue={externalId}
                        iconStyle={{ color: 'var(--color-accent)' }}
                        iconSize="xsmall"
                        description="external ID"
                        className="text-xs text-muted"
                    >
                        {externalId}
                    </CopyToClipboardInline>
                ) : null}
            </div>
        </div>
    )
}
