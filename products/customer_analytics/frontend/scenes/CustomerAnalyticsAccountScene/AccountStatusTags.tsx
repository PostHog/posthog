import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { AccountApi } from '../../generated/api.schemas'

function formatStatusDate(date: string): string {
    return dayjs(date).format('MMM D, YYYY')
}

export function AccountStatusTags({ account }: { account: AccountApi }): JSX.Element | null {
    if (!account.churned_at && !account.ignored_at) {
        return null
    }

    return (
        <div className="flex items-center gap-2">
            {account.churned_at ? (
                <Tooltip title={`Churned on ${formatStatusDate(account.churned_at)}`}>
                    <LemonTag type="danger" data-attr="account-churned-tag">
                        Churned
                    </LemonTag>
                </Tooltip>
            ) : null}
            {account.ignored_at ? (
                <Tooltip title={`Ignored since ${formatStatusDate(account.ignored_at)}`}>
                    <LemonTag type="warning" data-attr="account-ignored-tag">
                        Ignored
                    </LemonTag>
                </Tooltip>
            ) : null}
        </div>
    )
}
