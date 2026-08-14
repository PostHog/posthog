import { useState } from 'react'

import { IconBell, IconClock, IconGraph, IconList, IconPulse, IconTarget } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'
import type { LemonTab } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { AlertSummaryBanner, AlertSummarySection } from 'products/alerts/frontend/components/AlertSummaryBanner'

interface EditAlertTabsProps {
    summary: { fires: string; cadence: string; notifies: string }
    summaryHeader?: React.ReactNode
    nameNode: React.ReactNode
    previewNode: React.ReactNode
    definitionNode: React.ReactNode
    triggerNode?: React.ReactNode
    scheduleNode?: React.ReactNode
    advancedNode?: React.ReactNode
    notifyNode: React.ReactNode
    historyNode: React.ReactNode | null
    observedLogsUrl?: string
    showCadence?: boolean
}

export function EditAlertTabs({
    summary,
    summaryHeader,
    nameNode,
    previewNode,
    definitionNode,
    triggerNode,
    scheduleNode,
    advancedNode,
    notifyNode,
    historyNode,
    observedLogsUrl,
    showCadence,
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
        triggerNode
            ? {
                  key: 'trigger',
                  label: (
                      <span className="flex items-center gap-1.5">
                          <IconTarget className="size-4" />
                          Trigger
                      </span>
                  ),
                  content: <div className="space-y-3 pt-3">{triggerNode}</div>,
              }
            : null,
        scheduleNode || advancedNode
            ? {
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
              }
            : null,
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
        observedLogsUrl
            ? {
                  key: 'observed-logs',
                  label: (
                      <span className="flex items-center gap-1.5">
                          <IconList className="size-4" />
                          Observed logs
                          <IconOpenInNew className="size-3" />
                      </span>
                  ),
                  link: observedLogsUrl,
                  linkTarget: '_blank',
              }
            : null,
    ]

    let activeSummarySection: AlertSummarySection | undefined
    if (activeKey === 'trigger') {
        activeSummarySection = 'monitor'
    } else if (['monitor', 'schedule', 'notify'].includes(activeKey)) {
        activeSummarySection = activeKey as AlertSummarySection
    }

    return (
        <div className="space-y-3">
            <AlertSummaryBanner
                summary={summary}
                header={summaryHeader}
                activeSection={activeSummarySection}
                showCadence={showCadence}
            />
            <LemonTabs tabs={tabs} activeKey={activeKey} onChange={setActiveKey} className="flex-1 min-h-0" />
        </div>
    )
}
