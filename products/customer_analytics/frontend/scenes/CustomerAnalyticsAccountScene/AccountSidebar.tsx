import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { tagsModel } from '~/models/tagsModel'

import type { AccountApi } from '../../generated/api.schemas'
import { openAccountDetailWorkInProgress } from './accountDetailWorkInProgress'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountSidebar({ account }: { account: AccountApi }): JSX.Element {
    const { tagsSaving } = useValues(customerAnalyticsAccountSceneLogic)
    const { updateTags } = useActions(customerAnalyticsAccountSceneLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    return (
        <aside
            className="w-full shrink-0 border-x bg-surface-primary flex flex-col @min-[56rem]/account-detail:w-56"
            data-attr="account-sidebar"
        >
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
