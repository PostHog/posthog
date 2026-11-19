import { ReactNode } from 'react'

import { IconPulse, IconWarning } from '@posthog/icons'

import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { PaneTab, PaneTabBar } from 'scenes/session-recordings/components/PaneTabBar'

import { SessionRecordingSidebarTab } from '~/types'

export const DEBUG_TAB_KEYS = [SessionRecordingSidebarTab.INSPECTOR, SessionRecordingSidebarTab.NETWORK_WATERFALL]

export function debugTabKeys(withLinkedIssues: boolean): SessionRecordingSidebarTab[] {
    return withLinkedIssues ? [...DEBUG_TAB_KEYS, SessionRecordingSidebarTab.LINKED_ISSUES] : DEBUG_TAB_KEYS
}

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
    [SessionRecordingSidebarTab.LINKED_ISSUES]: {
        label: 'Linked issues',
        icon: <IconWarning />,
        dataAttr: 'watch-panel-debug-linked-issues',
    },
}

export function debugPaneTabs<K extends SessionRecordingSidebarTab>(tabs: K[]): PaneTab<K>[] {
    return tabs.flatMap((tab) => {
        const debugTab = DEBUG_TABS[tab]
        return debugTab ? [{ key: tab, ...debugTab }] : []
    })
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
    return (
        <PaneTabBar tabs={debugPaneTabs(tabs)} activeKey={activeTab} onChange={onChange}>
            {children}
        </PaneTabBar>
    )
}
