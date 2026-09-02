import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountDetailView, AccountDetailWidgetKind } from '../accountDetailViews'
import { accountDetailViewsLogic } from '../accountDetailViewsLogic'
import { customerAnalyticsAccountSceneLogic } from '../customerAnalyticsAccountSceneLogic'
import { AddViewDialog } from '../dialogs/AddViewDialog'
import { AddWidgetDialog } from '../dialogs/AddWidgetDialog'
import { ConfigureTabsDialog } from '../dialogs/ConfigureTabsDialog'
import { AccountRelatedPeopleWidget } from '../widgets/AccountRelatedPeopleWidget'
import { AccountSummaryWidget } from '../widgets/AccountSummaryWidget'
import { AccountSupportTicketsWidget } from '../widgets/AccountSupportTicketsWidget'
import { AccountTextWidget } from '../widgets/AccountTextWidget'
import { AccountUsageWidget } from '../widgets/AccountUsageWidget'

interface AccountDetailCanvasProps {
    account: AccountApi
}

function AccountWidget({
    kind,
    view,
    account,
    groupTypeIndex,
    onRemove,
}: {
    kind: AccountDetailWidgetKind
    view: AccountDetailView
    account: AccountApi
    groupTypeIndex: number | null
    onRemove: () => void
}): JSX.Element {
    switch (kind) {
        case 'text':
            return <AccountTextWidget view={view} onRemove={onRemove} />
        case 'summary':
            return <AccountSummaryWidget accountId={account.id} onRemove={onRemove} />
        case 'usage':
            return (
                <AccountUsageWidget
                    accountId={account.id}
                    externalId={account.external_id ?? null}
                    groupTypeIndex={groupTypeIndex}
                    onRemove={onRemove}
                />
            )
        case 'support_tickets':
            return <AccountSupportTicketsWidget accountId={account.id} onRemove={onRemove} />
        case 'related_people':
            return <AccountRelatedPeopleWidget externalId={account.external_id ?? null} onRemove={onRemove} />
    }
}

export function AccountDetailCanvas({ account }: AccountDetailCanvasProps): JSX.Element {
    const { selectedView, groupTypeIndex } = useValues(customerAnalyticsAccountSceneLogic)
    const { selectView } = useActions(customerAnalyticsAccountSceneLogic)
    const { pinnedViews, viewRows, viewsLoadFailed, viewSaving } = useValues(accountDetailViewsLogic)
    const { loadViews, removeWidget, setConfigureTabsOpen, setAddViewOpen, setAddWidgetOpen } =
        useActions(accountDetailViewsLogic)

    const viewsLoaded = viewRows !== null
    const tabs = pinnedViews.map((view) => ({
        key: view.id,
        label: view.name,
        'data-attr': 'account-detail-view-tab',
    }))
    // The active view is always a tab, even when it is reached only from Configure tabs.
    if (selectedView && !pinnedViews.includes(selectedView)) {
        tabs.push({ key: selectedView.id, label: selectedView.name, 'data-attr': 'account-detail-view-tab' })
    }

    return (
        <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-surface-secondary" data-attr="account-detail-canvas">
            <div className="shrink-0 bg-surface-primary border-b px-3">
                <LemonTabs
                    activeKey={selectedView?.id ?? ''}
                    onChange={selectView}
                    tabs={tabs}
                    size="small"
                    barClassName="mb-0"
                    rightSlot={
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconGear />}
                                onClick={() => setConfigureTabsOpen(true)}
                                disabledReason={!viewsLoaded ? 'Loading views…' : undefined}
                                data-attr="account-detail-configure-tabs"
                            >
                                Configure tabs
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={() => setAddViewOpen(true)}
                                disabledReason={!viewsLoaded ? 'Loading views…' : undefined}
                                data-attr="account-detail-add-view"
                            >
                                Add view
                            </LemonButton>
                        </>
                    }
                    rightSlotClassName="bg-surface-primary pr-0 py-1"
                />
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-3 @container">
                {viewsLoadFailed ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadViews }}>
                        Couldn't load views for this account. Try again.
                    </LemonBanner>
                ) : !viewsLoaded || !selectedView ? (
                    <div className="flex flex-col gap-3">
                        <LemonSkeleton className="h-6 w-48" />
                        <LemonSkeleton className="h-40 w-full" />
                    </div>
                ) : (
                    <>
                        <div className="flex items-center gap-2 mb-3">
                            <span className="text-xs text-secondary">
                                Viewing <span className="font-semibold text-primary">{selectedView.name}</span> ·{' '}
                                {selectedView.scope === 'team' ? 'team view' : 'your view'}
                            </span>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                className="ml-auto"
                                onClick={() => setAddWidgetOpen(true)}
                                loading={viewSaving}
                                disabledReason={viewSaving ? 'Saving…' : undefined}
                                data-attr="account-detail-add-widget"
                            >
                                Add widget
                            </LemonButton>
                        </div>
                        <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3 items-start">
                            {selectedView.widgets.map((kind) => (
                                <AccountWidget
                                    key={kind}
                                    kind={kind}
                                    view={selectedView}
                                    account={account}
                                    groupTypeIndex={groupTypeIndex}
                                    onRemove={() => removeWidget(selectedView.id, kind)}
                                />
                            ))}
                        </div>
                    </>
                )}
            </div>
            <ConfigureTabsDialog />
            <AddViewDialog />
            <AddWidgetDialog view={selectedView} />
        </div>
    )
}
