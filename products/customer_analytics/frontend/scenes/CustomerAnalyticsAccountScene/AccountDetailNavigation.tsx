import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { accountBillingLogic } from '../../components/Accounts/accountBillingLogic'
import { AccountViewComponent } from '../../components/Accounts/AccountViewComponent'
import type { AccountDetailTabsConfigApi } from '../../generated/api.schemas'
import {
    getAccountTabIdFromRoute,
    getAccountTabRoute,
    getDefaultAccountTabId,
    listAccountTabs,
    listVisibleAccountTabs,
    type AccountTabDefinition,
} from './accountTabs'
import { AccountViewRenderer } from './AccountViewRenderer'
import { accountViewsLogic } from './accountViewsLogic'

interface AccountDetailNavigationProps {
    projectId: number
    accountId: string
    externalId: string
    requestedTab: string
    onChange: (tab: string) => void
}

export function AccountDetailNavigation({
    projectId,
    accountId,
    externalId,
    requestedTab,
    onChange,
}: AccountDetailNavigationProps): JSX.Element {
    useMountedLogic(accountBillingLogic({ accountId, externalId, kind: 'usage' }))
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const logic = accountViewsLogic({ projectId })
    const { views, accountDetailTabs, viewsError, viewsLoading } = useValues(logic)
    const { openEditEditor, openConfigure, loadViews } = useActions(logic)
    const accountViewsEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]
    const tabs = listAccountTabs(featureFlags, accountViewsEnabled ? views : [])
    const requestedTabIdFromRoute = requestedTab ? getAccountTabIdFromRoute(requestedTab) : undefined
    const requestedTabId =
        requestedTabIdFromRoute?.startsWith('view:') && !accountViewsEnabled ? undefined : requestedTabIdFromRoute
    const activeTabId = requestedTabId ?? getDefaultAccountTabId(tabs, accountDetailTabs)
    const activeTab = tabs.find((tab) => tab.id === activeTabId)
    const loadingView = activeTabId.startsWith('view:') && !activeTab && viewsLoading && accountViewsEnabled
    const missingView = activeTabId.startsWith('view:') && !activeTab && !loadingView
    const visibleTabs = listVisibleAccountTabs(tabs, accountDetailTabs, activeTabId, user?.id)
    const tabDefinitions = loadingView
        ? [
              ...visibleTabs,
              {
                  id: activeTabId,
                  routeKey: activeTabId,
                  label: 'Loading view',
                  kind: 'view' as const,
              },
          ]
        : missingView
          ? [
                ...visibleTabs,
                {
                    id: activeTabId,
                    routeKey: activeTabId,
                    label: 'View unavailable',
                    kind: 'view' as const,
                },
            ]
          : visibleTabs

    const displayedTab = tabDefinitions.find((tab) => tab.id === activeTabId)
    const rightSlot = activeTab?.view ? (
        <div className="flex items-center gap-2">
            {activeTab.view.visibility === 'team' ? <LemonTag type="muted">Team</LemonTag> : null}
            {activeTab.view.can_edit ? (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconPencil />}
                    onClick={() => openEditEditor(activeTab.view!)}
                    data-attr="account-view-edit"
                >
                    Edit view
                </LemonButton>
            ) : null}
        </div>
    ) : undefined

    return (
        <div className="min-w-0">
            {viewsError && accountViewsEnabled ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadViews }} className="mb-2">
                    Couldn't load account views. System tabs are still available.
                </LemonBanner>
            ) : null}
            <div className="sticky top-0 z-10 bg-primary">
                <LemonTabs
                    key={JSON.stringify(tabDefinitions.map(({ id, label }) => [id, label]))}
                    activeKey={activeTabId}
                    onChange={(tabId) => onChange(getAccountTabRoute(tabId))}
                    rightSlotClassName="pr-0"
                    size="small"
                    rightSlot={rightSlot}
                    tabs={tabDefinitions.map((tab) => ({
                        key: tab.id,
                        label: tab.label,
                    }))}
                />
            </div>
            {displayedTab ? (
                <div key={activeTabId}>
                    {renderTabContent({
                        tab: displayedTab,
                        accountId,
                        externalId,
                        accountDetailTabs,
                        loadingViewId: loadingView ? activeTabId : undefined,
                        openConfigure: accountViewsEnabled ? openConfigure : undefined,
                    })}
                </div>
            ) : null}
        </div>
    )
}

interface RenderTabContentProps {
    tab: AccountTabDefinition
    accountId: string
    externalId: string
    accountDetailTabs: AccountDetailTabsConfigApi
    loadingViewId?: string
    openConfigure?: (config: RenderTabContentProps['accountDetailTabs']) => void
}

function renderTabContent({
    tab,
    accountId,
    externalId,
    accountDetailTabs,
    loadingViewId,
    openConfigure,
}: RenderTabContentProps): ReactNode {
    if (tab.id === loadingViewId) {
        return <LemonSkeleton className="my-3 h-40" />
    }
    if (tab.systemKind) {
        return (
            <AccountViewComponent
                kind={tab.systemKind}
                accountId={accountId}
                externalId={externalId}
                embedded={false}
            />
        )
    }
    if (tab.view) {
        return <AccountViewRenderer view={tab.view} accountId={accountId} externalId={externalId} />
    }
    return (
        <LemonBanner
            type="warning"
            action={
                openConfigure
                    ? { children: 'Open tab settings', onClick: () => openConfigure(accountDetailTabs) }
                    : undefined
            }
        >
            This view was deleted or you no longer have access to it. Choose another tab.
        </LemonBanner>
    )
}
