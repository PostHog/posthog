import { useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accountBillingLogic } from './accountBillingLogic'
import { AccountExpansionTab, getVisibleAccountExpansionTab } from './accountsExpansionLogic'
import { AccountViewComponent } from './AccountViewComponent'
import { listAvailableAccountViewComponents } from './accountViewComponents'

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
    useMountedLogic(accountBillingLogic({ accountId, externalId, kind: 'usage' }))
    const { featureFlags } = useValues(featureFlagLogic)
    const visibleActiveTab = getVisibleAccountExpansionTab(activeTab, featureFlags)
    const components = listAvailableAccountViewComponents(featureFlags)

    return (
        <LemonTabs
            activeKey={visibleActiveTab}
            onChange={onChange}
            size="small"
            rightSlot={rightSlot}
            tabs={components.map((component) => ({
                key: component.kind,
                label: component.label,
                content: (
                    <AccountViewComponent
                        kind={component.kind}
                        accountId={accountId}
                        externalId={externalId}
                        embedded={embedded}
                    />
                ),
            }))}
        />
    )
}
