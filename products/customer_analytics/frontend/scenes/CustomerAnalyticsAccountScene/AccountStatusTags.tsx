import { useActions } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getAccountStatusTags } from '../../components/Accounts/accountStatusTags'
import type { AccountApi } from '../../generated/api.schemas'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountStatusTags({ account }: { account: AccountApi }): JSX.Element | null {
    const { openAccountEditor } = useActions(customerAnalyticsAccountSceneLogic)
    const statusTags = getAccountStatusTags(account)

    if (statusTags.length === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-2">
            {statusTags.map(({ field, label, type, dateLabel, dataAttr }) => (
                <Tooltip key={field} title={dateLabel}>
                    <button type="button" className="inline-flex cursor-pointer" onClick={openAccountEditor}>
                        <LemonTag type={type} data-attr={dataAttr}>
                            {label}
                        </LemonTag>
                    </button>
                </Tooltip>
            ))}
        </div>
    )
}
