import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccountEventStreamToggle } from '../EventStream/AccountEventStreamToggle'
import { AccountBillingExpansion } from './AccountBillingExpansion'
import { AccountConversationsExpansion } from './AccountConversationsExpansion'
import { AccountFeatureRequestsExpansion } from './AccountFeatureRequestsExpansion'
import { AccountMeetingsExpansion } from './AccountMeetingsExpansion'
import { AccountNotesExpansion } from './AccountNotesExpansion'
import { AccountOpportunitiesExpansion } from './AccountOpportunitiesExpansion'
import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'
import { AccountRelationshipsExpansion } from './AccountRelationshipsExpansion'
import { AccountExpansionTab, getVisibleAccountExpansionTab } from './accountsExpansionLogic'

interface AccountDetailTabsProps {
    accountId: string
    externalId: string
    activeTab: AccountExpansionTab
    onChange: (tab: AccountExpansionTab) => void
    rightSlot?: ReactNode
    embedded?: boolean
}

export function AccountDetailTabs({
    accountId,
    externalId,
    activeTab,
    onChange,
    rightSlot,
    embedded = true,
}: AccountDetailTabsProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const visibleActiveTab = getVisibleAccountExpansionTab(activeTab, featureFlags)

    return (
        <LemonTabs
            activeKey={visibleActiveTab}
            onChange={onChange}
            size="small"
            rightSlot={rightSlot}
            tabs={[
                {
                    key: 'notes',
                    label: 'Notes',
                    content: <AccountNotesExpansion accountId={accountId} embedded={embedded} />,
                },
                {
                    key: 'users',
                    label: 'Users',
                    content: <AccountRelatedUsersExpansion externalId={externalId} embedded={embedded} />,
                },
                {
                    key: 'relationships',
                    label: 'Relationships',
                    content: <AccountRelationshipsExpansion accountId={accountId} embedded={embedded} />,
                },
                !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS] && {
                    key: 'feature_requests' as const,
                    label: 'Feature requests',
                    content: <AccountFeatureRequestsExpansion accountId={accountId} embedded={embedded} />,
                },
                {
                    key: 'usage',
                    label: 'Usage',
                    content: (
                        <AccountBillingExpansion
                            accountId={accountId}
                            externalId={externalId}
                            kind="usage"
                            embedded={embedded}
                        />
                    ),
                },
                {
                    key: 'spend',
                    label: 'Spend',
                    content: (
                        <AccountBillingExpansion
                            accountId={accountId}
                            externalId={externalId}
                            kind="spend"
                            embedded={embedded}
                        />
                    ),
                },
                {
                    key: 'opportunities',
                    label: 'Opportunities',
                    content: <AccountOpportunitiesExpansion accountId={accountId} embedded={embedded} />,
                },
                {
                    key: 'conversations',
                    label: 'Conversations',
                    content: <AccountConversationsExpansion accountId={accountId} embedded={embedded} />,
                },
                // Flag-gated here (not just inside the component) so the tab label hides too.
                !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP] && {
                    key: 'meetings' as const,
                    label: 'Meetings',
                    content: <AccountMeetingsExpansion accountId={accountId} embedded={embedded} />,
                },
                !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP] && {
                    key: 'event_stream' as const,
                    label: 'Event stream',
                    content: <AccountEventStreamToggle accountId={accountId} externalId={externalId} />,
                },
            ]}
        />
    )
}
