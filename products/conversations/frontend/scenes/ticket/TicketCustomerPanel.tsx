import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

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
// related groups. When both exist, the header row itself is the Account / Related groups selector (account
// preferred); when only one exists it renders a plain titled header, exactly like the standalone panels.
//
// Built as a custom frame rather than LemonCollapse because the collapse header is a <button>, and nesting
// the segmented control's buttons inside it would be invalid markup. The LemonCollapse CSS classes are
// reused so the frame looks identical to the other sidebar panels.
export function TicketCustomerPanel({
    ticketId,
    personUuid,
    organizationId,
    accountEnabled,
}: TicketCustomerPanelProps): JSX.Element | null {
    const { account, activeTab, panelOpen } = useValues(ticketCustomerPanelLogic({ ticketId, accountEnabled }))
    const { setActiveTab, setPanelOpen } = useActions(ticketCustomerPanelLogic({ ticketId, accountEnabled }))

    const accountAvailable = !!account
    const relatedAvailable = !!personUuid

    if (!accountAvailable && !relatedAvailable) {
        return null
    }

    const showTabs = accountAvailable && relatedAvailable
    // Guard the resolved tab against availability so a stale override can't select a missing tab.
    const showAccount = accountAvailable && (activeTab === 'account' || !relatedAvailable)
    const title = accountAvailable && !relatedAvailable ? 'Account' : 'Related groups'

    const collapseIcon = (
        <LemonButton
            size="small"
            icon={panelOpen ? <IconCollapse /> : <IconExpand />}
            onClick={(e) => {
                e.stopPropagation()
                setPanelOpen(!panelOpen)
            }}
            aria-label={panelOpen ? 'Collapse customer panel' : 'Expand customer panel'}
        />
    )

    return (
        <div className="LemonCollapse bg-surface-primary">
            <div className="LemonCollapsePanel">
                <div
                    className={clsx(
                        'LemonCollapsePanel__header flex items-center gap-2 pl-1 pr-2 py-1',
                        !showTabs && 'cursor-pointer'
                    )}
                    onClick={!showTabs ? () => setPanelOpen(!panelOpen) : undefined}
                >
                    {collapseIcon}
                    {showTabs ? (
                        <div className="flex-1 min-w-0">
                            <LemonSegmentedButton
                                fullWidth
                                size="small"
                                value={showAccount ? 'account' : 'related'}
                                onChange={(tab) => setActiveTab(tab)}
                                options={[
                                    { value: 'account' as const, label: 'Account' },
                                    { value: 'related' as const, label: 'Related groups' },
                                ]}
                            />
                        </div>
                    ) : (
                        <span className="flex-1 font-semibold">{title}</span>
                    )}
                </div>
                {panelOpen && (
                    <div className="LemonCollapsePanel__content border-t">
                        {showAccount && account ? (
                            <TicketAccountDetails account={account} />
                        ) : personUuid ? (
                            <RelatedGroupsPanel
                                personUuid={personUuid}
                                organizationId={organizationId}
                                renderCollapse={false}
                            />
                        ) : null}
                    </div>
                )}
            </div>
        </div>
    )
}
