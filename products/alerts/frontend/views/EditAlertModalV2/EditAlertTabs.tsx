import { useState } from 'react'

import { IconBell, IconClock, IconGraph, IconPulse } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'
import type { LemonTab } from '@posthog/lemon-ui'

import { AlertSummaryBanner, AlertSummarySection } from 'products/alerts/frontend/components/AlertSummaryBanner'

interface EditAlertTabsProps {
    summary: { fires: string; cadence: string; notifies: string }
    summaryHeader?: React.ReactNode
    nameNode: React.ReactNode
    previewNode: React.ReactNode
    definitionNode: React.ReactNode
    scheduleNode: React.ReactNode
    advancedNode: React.ReactNode
    notifyNode: React.ReactNode
    historyNode: React.ReactNode | null
}

export function EditAlertTabs({
    summary,
    summaryHeader,
    nameNode,
    previewNode,
    definitionNode,
    scheduleNode,
    advancedNode,
    notifyNode,
    historyNode,
}: EditAlertTabsProps): JSX.Element {
    const [activeKey, setActiveKey] = useState<string>('monitor')

    const tabs: (LemonTab<string> | null)[] = [
        {
            key: 'monitor',
            label: (
                <span className="flex items-center gap-1.5">
                    <IconPulse className="size-4" />
                    Monitor
                </span>
            ),
            content: (
                <div className="space-y-3 pt-3">
                    {nameNode}
                    {previewNode}
                    {definitionNode}
                </div>
            ),
        },
        {
            key: 'schedule',
            label: (
                <span className="flex items-center gap-1.5">
                    <IconClock className="size-4" />
                    Schedule
                </span>
            ),
            content: (
                <div className="space-y-3 pt-3">
                    {scheduleNode}
                    {advancedNode}
                </div>
            ),
        },
        {
            key: 'notify',
            label: (
                <span className="flex items-center gap-1.5">
                    <IconBell className="size-4" />
                    Notify
                </span>
            ),
            content: <div className="pt-3">{notifyNode}</div>,
        },
        historyNode
            ? {
                  key: 'history',
                  label: (
                      <span className="flex items-center gap-1.5">
                          <IconGraph className="size-4" />
                          History
                      </span>
                  ),
                  content: <div className="pt-3">{historyNode}</div>,
              }
            : null,
    ]

    let activeSummarySection: AlertSummarySection | undefined
    if (['monitor', 'schedule', 'notify'].includes(activeKey)) {
        activeSummarySection = activeKey as AlertSummarySection
    }

    return (
        <div className="space-y-3">
            <AlertSummaryBanner summary={summary} header={summaryHeader} activeSection={activeSummarySection} />
            <LemonTabs tabs={tabs} activeKey={activeKey} onChange={setActiveKey} className="flex-1 min-h-0" />
        </div>
    )
}
