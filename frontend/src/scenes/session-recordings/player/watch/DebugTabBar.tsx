import { ReactNode } from 'react'

import { IconPulse } from '@posthog/icons'

import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { PaneTabBar } from 'scenes/session-recordings/components/PaneTabBar'

import { SessionRecordingSidebarTab } from '~/types'

export const DEBUG_TAB_KEYS = [SessionRecordingSidebarTab.INSPECTOR, SessionRecordingSidebarTab.NETWORK_WATERFALL]

const DEBUG_TABS: Partial<Record<SessionRecordingSidebarTab, { label: string; icon: ReactNode; dataAttr: string }>> = {
    [SessionRecordingSidebarTab.INSPECTOR]: {
        label: 'Inspector',
        icon: <IconUnverifiedEvent />,
        dataAttr: 'watch-panel-debug-inspector',
    },
    [SessionRecordingSidebarTab.NETWORK_WATERFALL]: {
        label: 'Network',
        icon: <IconPulse />,
        dataAttr: 'watch-panel-debug-network',
    },
}

export function DebugTabBar({
    tabs,
    activeTab,
    onChange,
    children,
}: {
    tabs: SessionRecordingSidebarTab[]
    activeTab: SessionRecordingSidebarTab
    onChange: (tab: SessionRecordingSidebarTab) => void
    children?: ReactNode
}): JSX.Element {
    const paneTabs = tabs.flatMap((tab) => {
        const debugTab = DEBUG_TABS[tab]
        return debugTab ? [{ key: tab, ...debugTab }] : []
    })
    return (
        <PaneTabBar tabs={paneTabs} activeKey={activeTab} onChange={onChange}>
            {children}
        </PaneTabBar>
    )
}
