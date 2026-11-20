import { Button } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AccountLogo } from './AccountLogo'
import type { AccountNameCellProps } from './AccountNameCell'

export function QuillAccountNameCell({
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
            <div className="flex flex-col items-start min-w-0">
                {accountId ? (
                    <Button
                        variant="link-foreground"
                        size="sm"
                        nativeButton={false}
                        className="font-semibold"
                        render={
                            <LinkPrimitive
                                to={urls.customerAnalyticsAccount(accountId)}
                                onClick={onClick}
                                target={target}
                            />
                        }
                    >
                        {name}
                    </Button>
                ) : (
                    <span className="font-semibold">{name}</span>
                )}
                {externalId ? (
                    <CopyToClipboardInline
                        explicitValue={externalId}
                        iconSize="xsmall"
                        description="external ID"
                        className="text-xs text-muted-foreground"
                    >
                        {externalId}
                    </CopyToClipboardInline>
                ) : null}
            </div>
        </div>
    )
}
