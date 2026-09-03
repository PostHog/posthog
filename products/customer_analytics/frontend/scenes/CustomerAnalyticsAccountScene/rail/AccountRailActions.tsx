import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBuilding, IconEllipsis, IconLightBulb, IconNotebook } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { accountLinksLogic } from 'products/customer_analytics/frontend/components/Accounts/accountLinksLogic'
import { accountNotebooksLogic } from 'products/customer_analytics/frontend/components/Accounts/accountNotebooksLogic'
import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'

import { customerAnalyticsAccountSceneLogic } from '../customerAnalyticsAccountSceneLogic'
import { AccountFeatureRequestComposer } from './AccountFeatureRequestComposer'

interface AccountRailActionsProps {
    accountId: string
}

export function AccountRailActions({ accountId }: AccountRailActionsProps): JSX.Element {
    const { createdNoteLoading } = useValues(accountNotebooksLogic({ accountId }))
    const { createNote } = useActions(accountNotebooksLogic({ accountId }))
    const { links } = useValues(accountLinksLogic({ accountId }))
    const { featureRequestComposerKey, featureRequestComposerOpen } = useValues(customerAnalyticsAccountSceneLogic)
    const { openFeatureRequestComposer } = useActions(customerAnalyticsAccountSceneLogic)

    const organizationLink = links.find((link) => link.key === 'organization')
    const overflowItems: LemonMenuItems = [
        {
            label: 'Copy link to account',
            onClick: () => {
                void copyToClipboard(
                    urls.absolute(urls.currentProject(urls.customerAnalyticsAccount(accountId))),
                    'account link'
                )
                posthog.capture(AccountsEvents.DetailRailActionClicked, { action: 'copy_link' })
            },
        },
        { label: 'Open the accounts list', to: urls.customerAnalyticsAccounts() },
        {
            title: 'Links',
            items: links
                .filter((link) => link.key !== 'organization')
                .map((link) => ({
                    label: link.label,
                    to: link.to ?? undefined,
                    targetBlank: link.targetBlank,
                    disabledReason: link.disabledReason ?? undefined,
                    onClick: () =>
                        posthog.capture(AccountsEvents.DetailRailActionClicked, { action: 'link', link_key: link.key }),
                })),
        },
    ]

    return (
        <div className="flex items-center gap-1.5 flex-wrap px-5 py-3" data-attr="account-rail-actions">
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconNotebook />}
                tooltip="Add note"
                aria-label="Add note"
                loading={createdNoteLoading}
                disabledReason={createdNoteLoading ? 'Creating note…' : undefined}
                onClick={() => {
                    posthog.capture(AccountsEvents.DetailRailActionClicked, { action: 'add_note' })
                    createNote()
                }}
                data-attr="account-rail-add-note"
            />
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconBuilding />}
                tooltip="Open the organization page"
                aria-label="Open the organization page"
                to={organizationLink?.to ?? undefined}
                disabledReason={organizationLink?.disabledReason ?? undefined}
                onClick={() => posthog.capture(AccountsEvents.DetailRailActionClicked, { action: 'org_page' })}
                data-attr="account-rail-org-page"
            />
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconLightBulb />}
                tooltip="Add feature request"
                aria-label="Add feature request"
                onClick={() => {
                    posthog.capture(AccountsEvents.DetailRailActionClicked, { action: 'add_feature_request' })
                    openFeatureRequestComposer()
                }}
                data-attr="account-rail-add-feature-request"
            />
            <LemonMenu items={overflowItems} placement="bottom-start">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconEllipsis />}
                    tooltip="More"
                    aria-label="More actions"
                    data-attr="account-rail-more"
                />
            </LemonMenu>
            {featureRequestComposerOpen ? (
                <AccountFeatureRequestComposer key={featureRequestComposerKey} accountId={accountId} />
            ) : null}
        </div>
    )
}
