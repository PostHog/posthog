import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { ActivityLogDiff } from './ActivityLogDiff'
import { HumanizedActivityLogItem } from './humanizeActivity'

export type QuillActivityLogTab = 'details' | 'extended description' | 'diff' | 'raw'

// Serializes only when the Raw tab renders, since payloads can be large and most rows stay collapsed.
function RawPayload({ value }: { value: unknown }): JSX.Element {
    return <pre>{JSON.stringify(value, null, 2)}</pre>
}

/** The tabs an expanded quill activity row shows. */
export function QuillActivityLogDetails({
    logItem,
    detailsId,
    activeTab,
    onTabChange,
}: {
    logItem: HumanizedActivityLogItem
    detailsId: string
    activeTab: QuillActivityLogTab
    onTabChange: (tab: QuillActivityLogTab) => void
}): JSX.Element {
    const tabs = [
        logItem.expandedView && {
            key: 'details' as const,
            label: logItem.expandedView.label,
            content: logItem.expandedView.content,
        },
        logItem.extendedDescription && {
            key: 'extended description' as const,
            label: 'Extended description',
            content: <div>{logItem.extendedDescription}</div>,
        },
        { key: 'diff' as const, label: 'Diff', content: <ActivityLogDiff logItem={logItem} /> },
        {
            key: 'raw' as const,
            label: 'Raw',
            content: <RawPayload value={logItem.unprocessed} />,
        },
    ].filter(Boolean) as { key: QuillActivityLogTab; label: string; content: React.ReactNode }[]

    return (
        <Tabs
            id={detailsId}
            value={activeTab}
            onValueChange={(value) => onTabChange(value as QuillActivityLogTab)}
            className="min-w-0 gap-2 px-2 pb-2 [&_pre]:whitespace-pre-wrap [&_pre]:break-words"
        >
            <TabsList>
                {tabs.map((tab) => (
                    <TabsTrigger key={tab.key} value={tab.key}>
                        {tab.label}
                    </TabsTrigger>
                ))}
            </TabsList>
            {tabs.map((tab) => (
                <TabsContent
                    key={tab.key}
                    value={tab.key}
                    // The shared diff titles each field with an h2, which reads as a page heading at this size.
                    className="min-w-0 overflow-x-auto [&_h2]:m-0 [&_h2]:text-xs [&_h2]:font-semibold"
                >
                    {tab.content}
                </TabsContent>
            ))}
        </Tabs>
    )
}
