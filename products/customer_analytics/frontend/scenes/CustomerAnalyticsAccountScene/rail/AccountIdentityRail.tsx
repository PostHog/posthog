import { useActions, useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

import { AccountLogo } from 'products/customer_analytics/frontend/components/Accounts/AccountLogo'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerAnalyticsAccountSceneLogic } from '../customerAnalyticsAccountSceneLogic'
import { AccountPinnedProperties } from './AccountPinnedProperties'
import { AccountRailActions } from './AccountRailActions'

interface AccountIdentityRailProps {
    account: AccountApi
}

export function AccountIdentityRail({ account }: AccountIdentityRailProps): JSX.Element {
    const { tagsSaving } = useValues(customerAnalyticsAccountSceneLogic)
    const { updateTags } = useActions(customerAnalyticsAccountSceneLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    return (
        <aside
            className="w-72 shrink-0 flex flex-col rounded border overflow-y-auto min-h-0 bg-surface-primary"
            data-attr="account-identity-rail"
        >
            <div className="flex items-start gap-2 px-5 pt-4 pb-3">
                <AccountLogo domain={account.properties?.website_domain} name={account.name} />
                <div className="min-w-0 flex flex-col">
                    <h2 className="text-lg font-semibold leading-tight mb-0 truncate">{account.name}</h2>
                    {account.external_id ? (
                        <CopyToClipboardInline
                            explicitValue={account.external_id}
                            description="external ID"
                            iconSize="xsmall"
                            className="font-mono text-xxs text-secondary"
                        >
                            {account.external_id}
                        </CopyToClipboardInline>
                    ) : (
                        <span className="font-mono text-xxs text-muted">No external ID</span>
                    )}
                </div>
            </div>
            <LemonDivider className="my-0" />
            <AccountRailActions accountId={account.id} />
            <div className="px-5 pb-4">
                <ObjectTags
                    tags={account.tags ?? []}
                    onChange={updateTags}
                    saving={tagsSaving}
                    tagsAvailable={tagsAvailable}
                    wrap
                    data-attr="account-rail-tags"
                />
            </div>
            <LemonDivider className="my-0 mx-5" />
            <AccountPinnedProperties accountId={account.id} account={account} />
        </aside>
    )
}
