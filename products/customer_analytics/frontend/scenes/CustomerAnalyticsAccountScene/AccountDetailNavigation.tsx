import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accountBillingLogic } from '../../components/Accounts/accountBillingLogic'
import { AccountViewComponent } from '../../components/Accounts/AccountViewComponent'
import { listAvailableAccountViewComponents } from '../../components/Accounts/accountViewComponents'
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
    const logic = accountViewsLogic({ projectId })
    const { views, viewsError, viewsLoading } = useValues(logic)
    const { openEditEditor, loadViews } = useActions(logic)
    const accountViewsEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]
    const systemTabs = listAvailableAccountViewComponents(featureFlags)
    const selectedViewId =
        accountViewsEnabled && requestedTab.startsWith('view:') ? requestedTab.slice('view:'.length) : null
    const selectedView = selectedViewId ? views.find((view) => view.id === selectedViewId) : undefined
    const selectedSystemTab = systemTabs.find((tab) => tab.kind === requestedTab) ?? systemTabs[0]
    const activeKey = selectedViewId ? `view:${selectedViewId}` : selectedSystemTab?.kind
    const loadingView = !!selectedViewId && !selectedView && viewsLoading

    return (
        <div className="min-w-0">
            {viewsError && accountViewsEnabled ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadViews }} className="mb-2">
                    Couldn't load account views. System tabs are still available.
                </LemonBanner>
            ) : null}
            <div className="sticky top-0 z-10 bg-primary">
                <LemonTabs
                    activeKey={activeKey}
                    onChange={onChange}
                    rightSlotClassName="pr-0"
                    size="small"
                    rightSlot={
                        selectedView ? (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={<IconPencil />}
                                onClick={() => openEditEditor(selectedView)}
                                data-attr="account-view-edit"
                            >
                                Edit view
                            </LemonButton>
                        ) : undefined
                    }
                    tabs={[
                        ...systemTabs.map((tab) => ({ key: tab.kind, label: tab.label })),
                        ...(accountViewsEnabled
                            ? views.map((view) => ({ key: `view:${view.id}`, label: view.name }))
                            : []),
                    ]}
                />
            </div>
            {loadingView ? (
                <LemonSkeleton className="my-3 h-40" />
            ) : selectedView ? (
                <AccountViewRenderer
                    view={selectedView}
                    projectId={projectId}
                    accountId={accountId}
                    externalId={externalId}
                />
            ) : selectedViewId && !viewsError ? (
                <LemonBanner type="warning" className="my-3">
                    This view was deleted or you no longer have access to it. Choose another tab.
                </LemonBanner>
            ) : selectedSystemTab ? (
                <AccountViewComponent
                    kind={selectedSystemTab.kind}
                    accountId={accountId}
                    externalId={externalId}
                    embedded={false}
                />
            ) : null}
        </div>
    )
}
