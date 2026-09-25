import { useActions, useValues } from 'kea'

import { IconLive, IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'

import type { AccountApi } from '../../generated/api.schemas'
import { AccountEditModal } from './AccountEditModal'
import { AccountPinnedPropertiesPanel } from './components/AccountPinnedPropertiesPanel'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountSidebar({ account }: { account: AccountApi }): JSX.Element {
    const { tagsSaving } = useValues(customerAnalyticsAccountSceneLogic)
    const { updateTags, openAccountEditor } = useActions(customerAnalyticsAccountSceneLogic)
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)

    return (
        <aside
            className="w-full shrink-0 @max-[60rem]:border @max-[60rem]:rounded border-r rounded-r bg-surface-primary flex flex-col @min-[60rem]/account-detail:h-full @min-[60rem]/account-detail:min-h-0 @min-[60rem]/account-detail:w-60 @min-[60rem]/account-detail:overflow-y-auto"
            data-attr="account-sidebar"
        >
            <div className="flex justify-center gap-2 p-4">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconLive />}
                    tooltip="Set up event stream"
                    aria-label="Set up event stream"
                    data-attr="account-sidebar-event-stream"
                    to={urls.customerAnalyticsConfiguration('customer-analytics-event-stream')}
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPencil />}
                    tooltip="Edit account"
                    aria-label="Edit account"
                    data-attr="account-sidebar-edit"
                    onClick={openAccountEditor}
                />
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-1 p-4" data-attr="account-rail-tags">
                <span className="secondary text-secondary">Tags</span>
                <ObjectTags
                    tags={account.tags ?? []}
                    onChange={updateTags}
                    onEdit={loadTagsIfNeeded}
                    saving={tagsSaving || tagsLoading}
                    tagsAvailable={tagsAvailable}
                    wrap
                />
            </div>
            <LemonDivider className="my-0" />
            <AccountPinnedPropertiesPanel accountId={account.id} />
            <AccountEditModal />
        </aside>
    )
}
