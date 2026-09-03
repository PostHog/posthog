import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    IconCloud,
    IconCopy,
    IconDatabase,
    IconGlobe,
    IconGraph,
    IconPeople,
    IconPiggyBank,
    IconReceipt,
} from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSkeleton, ProfilePicture } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { accountBillingLogic } from './accountBillingLogic'
import { accountConversationsLogic } from './accountConversationsLogic'
import { AccountDetailTabs } from './AccountDetailTabs'
import { accountEmailThreadsLogic } from './accountEmailThreadsLogic'
import { accountLinksLogic } from './accountLinksLogic'
import { accountMeetingsLogic } from './accountMeetingsLogic'
import { accountNotebooksLogic } from './accountNotebooksLogic'
import { accountOpportunitiesLogic } from './accountOpportunitiesLogic'
import { accountRelatedUsersLogic } from './accountRelatedUsersLogic'
import { accountRelationshipsLogic } from './accountRelationshipsLogic'
import { accountsExpansionLogic } from './accountsExpansionLogic'
import { accountSummariesLogic } from './accountSummariesLogic'
import { AccountsEvents } from './constants'
import { EditAccountLinksButton } from './EditAccountLinksButton'

const LINK_ICONS: Record<string, JSX.Element> = {
    website: <IconGlobe />,
    organization: <IconPeople />,
    revenue: <IconPiggyBank />,
    'usage-dashboard': <IconGraph />,
    metabase: <IconDatabase />,
    slack: <IconSlack />,
    'billing-admin': <IconReceipt />,
    salesforce: <IconCloud />,
}

function ActiveRelationships({ accountId }: { accountId: string }): JSX.Element | null {
    const { activeRelationships } = useValues(accountRelationshipsLogic({ accountId }))
    if (activeRelationships.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <h4 className="secondary uppercase text-secondary mb-0">Relationships</h4>
            {activeRelationships.map((relationship) => (
                <div key={relationship.id} className="flex flex-col gap-1">
                    <LemonLabel>{relationship.definition.name}</LemonLabel>
                    <div className="flex items-center gap-2 border rounded px-2 py-1.5 bg-bg-light">
                        {relationship.user ? (
                            <>
                                <ProfilePicture user={{ email: relationship.user.email }} size="sm" />
                                <span className="text-sm">{relationship.user.email}</span>
                            </>
                        ) : (
                            <span className="text-sm text-muted italic">Deleted user</span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    )
}

function UsefulLinks({ accountId }: { accountId: string }): JSX.Element {
    const { links, accountLoading } = useValues(accountLinksLogic({ accountId }))
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1 mb-1">
                <h4 className="secondary uppercase text-secondary mb-0">Useful links</h4>
                <EditAccountLinksButton accountId={accountId} />
            </div>
            {accountLoading ? (
                <>
                    <LemonSkeleton className="h-7 w-32" />
                    <LemonSkeleton className="h-7 w-32" />
                    <LemonSkeleton className="h-7 w-32" />
                </>
            ) : (
                links.map((link) => (
                    <LemonButton
                        key={link.key}
                        type="tertiary"
                        size="small"
                        fullWidth
                        icon={LINK_ICONS[link.key]}
                        to={link.to ?? undefined}
                        targetBlank={link.targetBlank}
                        disabledReason={link.disabledReason ?? undefined}
                        onClick={() =>
                            posthog.capture(AccountsEvents.LinkClicked, {
                                link_key: link.key,
                                has_destination: !!link.to,
                            })
                        }
                    >
                        {link.label}
                    </LemonButton>
                ))
            )}
            <LemonButton
                type="tertiary"
                size="small"
                fullWidth
                icon={<IconCopy />}
                onClick={() => {
                    void copyToClipboard(
                        urls.absolute(urls.currentProject(urls.customerAnalyticsAccount(accountId))),
                        'link to this account'
                    )
                    posthog.capture(AccountsEvents.LinkClicked, {
                        link_key: 'copy-account-link',
                        has_destination: true,
                    })
                }}
            >
                Copy link to account
            </LemonButton>
        </div>
    )
}

export function AccountNotebooksExpansion({
    accountId,
    externalId,
}: {
    accountId: string
    externalId: string
}): JSX.Element {
    // AccountDetailTabs only renders the active tab, so these mounts keep expanded-row data cached between tab switches.
    useMountedLogic(accountNotebooksLogic({ accountId }))
    useMountedLogic(accountRelatedUsersLogic({ externalId }))
    useMountedLogic(accountRelationshipsLogic({ accountId }))
    useMountedLogic(accountBillingLogic({ accountId, externalId, kind: 'usage' }))
    useMountedLogic(accountBillingLogic({ accountId, externalId, kind: 'spend' }))
    useMountedLogic(accountOpportunitiesLogic({ accountId }))
    useMountedLogic(accountSummariesLogic({ accountId }))
    useMountedLogic(accountConversationsLogic({ accountId }))
    useMountedLogic(accountEmailThreadsLogic({ accountId }))
    useMountedLogic(accountMeetingsLogic({ accountId }))
    const { activeTabFor } = useValues(accountsExpansionLogic)
    const { setActiveTab } = useActions(accountsExpansionLogic)
    const activeTab = activeTabFor(accountId)

    return (
        <div
            className="sticky left-0 w-[100cqw] max-w-full overflow-x-hidden p-3 bg-bg-light"
            data-attr="account-expansion"
        >
            <div className="flex gap-4">
                <div className="w-fit shrink-0 flex flex-col gap-4">
                    <UsefulLinks accountId={accountId} />
                    <ActiveRelationships accountId={accountId} />
                </div>
                <div className="flex-1 min-w-0">
                    <AccountDetailTabs
                        accountId={accountId}
                        externalId={externalId}
                        activeTab={activeTab}
                        onChange={(tab) => setActiveTab(accountId, tab)}
                    />
                </div>
            </div>
        </div>
    )
}
