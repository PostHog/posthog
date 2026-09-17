import { useActions, useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

import type { AccountApi } from '../../generated/api.schemas'
import { AccountPinnedPropertiesPanel } from './components/AccountPinnedPropertiesPanel'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountSidebar({ account }: { account: AccountApi }): JSX.Element {
    const { tagsSaving } = useValues(customerAnalyticsAccountSceneLogic)
    const { updateTags } = useActions(customerAnalyticsAccountSceneLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    return (
        <aside
            className="w-full shrink-0 @max-[60rem]:border @max-[60rem]:rounded border-r rounded-r bg-surface-primary flex flex-col @min-[60rem]/account-detail:h-full @min-[60rem]/account-detail:min-h-0 @min-[60rem]/account-detail:w-60 @min-[60rem]/account-detail:overflow-y-auto"
            data-attr="account-sidebar"
        >
            <div className="flex flex-col gap-1 p-4" data-attr="account-rail-tags">
                <span className="secondary text-secondary">Tags</span>
                <ObjectTags
                    tags={account.tags ?? []}
                    onChange={updateTags}
                    saving={tagsSaving}
                    tagsAvailable={tagsAvailable}
                    wrap
                />
            </div>
            <LemonDivider className="my-0" />
            <AccountPinnedPropertiesPanel accountId={account.id} />
        </aside>
    )
}
