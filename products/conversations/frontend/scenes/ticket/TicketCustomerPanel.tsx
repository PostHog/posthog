import { useActions, useValues } from 'kea'

import { LemonCollapse, LemonSegmentedButton } from '@posthog/lemon-ui'

import { RelatedGroupsPanel } from './RelatedGroupsPanel'
import { TicketAccountDetails } from './TicketAccountDetails'
import { ticketCustomerPanelLogic } from './ticketCustomerPanelLogic'

interface TicketCustomerPanelProps {
    ticketId: string
    personUuid?: string | null
    // Organization group key snapshotted at creation, used by the related-groups tab.
    organizationId?: string | null
    // Whether the linked customer analytics account may be shown (feature flag + org gating done by caller).
    accountEnabled: boolean
}

// One collapsible panel holding the customer context: the customer analytics account and the person's
// related groups. When both exist they share a tab toggle (account preferred); when only one exists it
// renders on its own, exactly as the standalone panels did.
export function TicketCustomerPanel({
    ticketId,
    personUuid,
    organizationId,
    accountEnabled,
}: TicketCustomerPanelProps): JSX.Element | null {
    const { account, activeTab } = useValues(ticketCustomerPanelLogic({ ticketId, accountEnabled }))
    const { setActiveTab } = useActions(ticketCustomerPanelLogic({ ticketId, accountEnabled }))

    const accountAvailable = !!account
    const relatedAvailable = !!personUuid

    if (!accountAvailable && !relatedAvailable) {
        return null
    }

    const showTabs = accountAvailable && relatedAvailable
    // Guard the resolved tab against availability so a stale override can't select a missing tab.
    const showAccount = accountAvailable && (activeTab === 'account' || !relatedAvailable)
    const header = showTabs ? 'Customer' : accountAvailable ? 'Account' : 'Related groups'

    const content = (
        <div className="flex flex-col gap-3">
            {showTabs && (
                <LemonSegmentedButton
                    fullWidth
                    size="small"
                    value={showAccount ? 'account' : 'related'}
                    onChange={setActiveTab}
                    options={[
                        { value: 'account' as const, label: 'Account' },
                        { value: 'related' as const, label: 'Related groups' },
                    ]}
                />
            )}
            {showAccount && account ? (
                <TicketAccountDetails account={account} />
            ) : personUuid ? (
                <RelatedGroupsPanel personUuid={personUuid} organizationId={organizationId} renderCollapse={false} />
            ) : null}
        </div>
    )

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="customer"
            panels={[{ key: 'customer', header, content }]}
        />
    )
}
