import { useState } from 'react'

import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillAlertSummaryBanner } from 'products/alerts/frontend/components/QuillAlertSummaryBanner'

import { EditAlertTab } from './EditAlertTabs'

interface QuillEditAlertTabsProps {
    summary: { fires: string; cadence: string; notifies: string }
    summaryHeader?: React.ReactNode
    statusNode?: React.ReactNode
    tabs: EditAlertTab[]
    showCadence?: boolean
}

export function QuillEditAlertTabs({
    summary,
    summaryHeader,
    statusNode,
    tabs,
    showCadence,
}: QuillEditAlertTabsProps): JSX.Element {
    const [activeKey, setActiveKey] = useState<string>('monitor')
    const activeSummarySection = tabs.find((tab) => tab.key === activeKey)?.summarySection
    const contentTabs = tabs.filter((tab) => 'content' in tab)
    const linkTabs = tabs.filter((tab) => !('content' in tab) && tab.link)

    return (
        <div className="flex flex-col gap-3">
            <QuillAlertSummaryBanner
                summary={summary}
                header={summaryHeader}
                activeSection={activeSummarySection}
                showCadence={showCadence}
            />
            {statusNode}
            <Tabs value={activeKey} onValueChange={(key) => setActiveKey(key as string)}>
                <div className="flex flex-wrap items-center gap-2">
                    <TabsList variant="line" className="max-w-full flex-wrap justify-start">
                        {contentTabs.map((tab) => (
                            <TabsTrigger key={tab.key} value={tab.key} disabled={!!tab.disabledReason}>
                                {tab.label}
                            </TabsTrigger>
                        ))}
                    </TabsList>
                    {linkTabs.map((tab) => (
                        <Button
                            key={tab.key}
                            variant="default"
                            nativeButton={false}
                            render={<LinkPrimitive to={tab.link} />}
                        >
                            {tab.label}
                        </Button>
                    ))}
                </div>
                {contentTabs.map((tab) => (
                    <TabsContent key={tab.key} value={tab.key}>
                        {'content' in tab ? tab.content : null}
                    </TabsContent>
                ))}
            </Tabs>
        </div>
    )
}
