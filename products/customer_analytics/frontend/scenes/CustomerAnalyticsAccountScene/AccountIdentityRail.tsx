import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

import { AccountLogo } from '../../components/Accounts/AccountLogo'
import type { AccountApi } from '../../generated/api.schemas'
import { openAccountDetailWorkInProgress } from './accountDetailWorkInProgress'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

function getAccountLogoDomain(account: AccountApi): string | null {
    return account.properties?.website_domain ?? account.properties?.email_domains?.[0] ?? null
}

export function AccountIdentityRail({ account }: { account: AccountApi }): JSX.Element {
    const { tagsSaving } = useValues(customerAnalyticsAccountSceneLogic)
    const { updateTags } = useActions(customerAnalyticsAccountSceneLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    return (
        <aside
            className="w-full shrink-0 rounded border bg-surface-primary flex flex-col @min-[56rem]/account-detail:w-56"
            data-attr="account-identity-rail"
        >
            <div className="flex items-start gap-2 min-w-0 p-4">
                <AccountLogo domain={getAccountLogoDomain(account)} name={account.name} />
                <div className="flex flex-col min-w-0 gap-1">
                    <h2 className="text-base font-semibold mb-0 break-words">{account.name}</h2>
                    {account.external_id ? (
                        <CopyToClipboardInline
                            explicitValue={account.external_id}
                            description="external ID"
                            className="text-xs text-muted break-all"
                        >
                            {account.external_id}
                        </CopyToClipboardInline>
                    ) : (
                        <span className="text-xs text-muted">External ID not set</span>
                    )}
                </div>
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-1 p-4" data-attr="account-rail-tags">
                <span className="text-xs text-secondary">Tags</span>
                <ObjectTags
                    tags={account.tags ?? []}
                    onChange={updateTags}
                    saving={tagsSaving}
                    tagsAvailable={tagsAvailable}
                    wrap
                />
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-3 p-4" data-attr="account-rail-properties">
                <div className="flex items-center gap-2">
                    <span className="text-xs text-secondary">Properties</span>
                    <LemonButton
                        size="xsmall"
                        icon={<IconGear />}
                        className="ml-auto"
                        tooltip="Configure properties"
                        aria-label="Configure properties"
                        onClick={() => openAccountDetailWorkInProgress('Configure properties')}
                        data-attr="account-detail-configure-properties"
                    />
                </div>
                <span className="text-sm text-muted">No properties pinned.</span>
            </div>
        </aside>
    )
}
