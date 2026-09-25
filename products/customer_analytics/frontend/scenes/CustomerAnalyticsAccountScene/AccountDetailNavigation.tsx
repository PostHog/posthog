import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconGlobe, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { accountBillingLogic } from '../../components/Accounts/accountBillingLogic'
import { AccountViewComponent } from '../../components/Accounts/AccountViewComponent'
import {
    getAccountTabIdFromRoute,
    getAccountTabRoute,
    getActiveAccountTabId,
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
    const { views, accountDetailTabs, config, configError, viewsError, viewsLoading } = useValues(logic)
    const { openEditEditor, openConfigure, loadViews } = useActions(logic)
    const accountViewsEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]
    const accountTabsEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_TABS]
    const tabs = listAccountTabs(featureFlags, accountViewsEnabled ? views : [])
    const requestedTabIdFromRoute = requestedTab ? getAccountTabIdFromRoute(requestedTab) : undefined
    const requestedTabId =
        requestedTabIdFromRoute?.startsWith('view:') && !accountViewsEnabled ? undefined : requestedTabIdFromRoute
    const activeTabId = getActiveAccountTabId(tabs, accountDetailTabs, requestedTabId, accountTabsEnabled)
    const activeTab = tabs.find((tab) => tab.id === activeTabId)
    const loadingView = activeTabId.startsWith('view:') && !activeTab && viewsLoading && accountViewsEnabled
    const viewLoadError = activeTabId.startsWith('view:') && !activeTab && !!viewsError && accountViewsEnabled
    const missingView = activeTabId.startsWith('view:') && !activeTab && !loadingView && !viewLoadError
    const visibleTabs = listVisibleAccountTabs(tabs, accountDetailTabs, activeTabId, user?.id, accountTabsEnabled)
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
    const rightSlot = activeTab?.view?.can_edit ? (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconPencil />}
            onClick={() => openEditEditor(activeTab.view!)}
            data-attr="account-view-edit"
        >
            Edit view
        </LemonButton>
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
                        label: getAccountTabLabel(tab),
                    }))}
                />
            </div>
            {viewLoadError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadViews }} className="my-3">
                    Couldn't load this view. Try again.
                </LemonBanner>
            ) : displayedTab ? (
                <div key={activeTabId}>
                    {renderTabContent({
                        tab: displayedTab,
                        projectId,
                        accountId,
                        externalId,
                        loadingViewId: loadingView ? activeTabId : undefined,
                        openConfigure: accountTabsEnabled
                            ? () => openConfigure(config && !configError ? accountDetailTabs : null)
                            : undefined,
                    })}
                </div>
            ) : null}
        </div>
    )
}

function getAccountTabLabel(tab: AccountTabDefinition): string | JSX.Element {
    if (tab.view?.visibility !== 'team') {
        return tab.label
    }

    return (
        <span className="flex items-center gap-1">
            <span>{tab.label}</span>
            <span className="sr-only">Shared with team</span>
            <Tooltip title="This view is shared with the team.">
                <IconGlobe className="shrink-0 text-muted" />
            </Tooltip>
        </span>
    )
}

interface RenderTabContentProps {
    tab: AccountTabDefinition
    projectId: number
    accountId: string
    externalId: string
    loadingViewId?: string
    openConfigure?: () => void
}

function renderTabContent({
    tab,
    projectId,
    accountId,
    externalId,
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
        return (
            <AccountViewRenderer view={tab.view} projectId={projectId} accountId={accountId} externalId={externalId} />
        )
    }
    return (
        <LemonBanner
            type="warning"
            action={openConfigure ? { children: 'Open tab settings', onClick: openConfigure } : undefined}
        >
            This view was deleted or you no longer have access to it. Choose another tab.
        </LemonBanner>
    )
}
