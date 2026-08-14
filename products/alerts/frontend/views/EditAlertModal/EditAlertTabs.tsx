import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'
import type { LemonTab } from '@posthog/lemon-ui'

import { AlertSummaryBanner, AlertSummarySection } from 'products/alerts/frontend/components/AlertSummaryBanner'

export type EditAlertTab = LemonTab<string> & { summarySection?: AlertSummarySection }

interface EditAlertTabsProps {
    summary: { fires: string; cadence: string; notifies: string }
    summaryHeader?: React.ReactNode
    statusNode?: React.ReactNode
    tabs: EditAlertTab[]
    showCadence?: boolean
}

export function EditAlertTabs({
    summary,
    summaryHeader,
    statusNode,
    tabs,
    showCadence,
}: EditAlertTabsProps): JSX.Element {
    const [activeKey, setActiveKey] = useState<string>('monitor')
    const activeSummarySection = tabs.find((tab) => tab.key === activeKey)?.summarySection

    return (
        <div className="space-y-3">
            <AlertSummaryBanner
                summary={summary}
                header={summaryHeader}
                activeSection={activeSummarySection}
                showCadence={showCadence}
            />
            {statusNode}
            <LemonTabs tabs={tabs} activeKey={activeKey} onChange={setActiveKey} className="flex-1 min-h-0" />
        </div>
    )
}
