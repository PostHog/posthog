import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { OverviewTab } from 'scenes/session-recordings/player/player-meta/overviewTabs'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { OVERVIEW_SNAPSHOT_SCOPE } from 'scenes/session-recordings/player/sidebar/overviewSnapshotScope'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'

import { QuillExperimentsSection } from './QuillExperimentsSection'
import { QuillOverviewDeviceCard } from './QuillOverviewDeviceCard'
import { QuillOverviewOtherWatchers } from './QuillOverviewOtherWatchers'
import { QuillOverviewPersonCard } from './QuillOverviewPersonCard'
import { QuillOverviewSessionCard } from './QuillOverviewSessionCard'
import { QuillSettingsSnapshot } from './QuillSettingsSnapshot'
import { QuillTTLWarning } from './QuillTTLWarning'

const WIDE_OVERVIEW_PX = 960

const OVERVIEW_TABS: { value: OverviewTab; label: string }[] = [
    { value: 'session', label: 'Session' },
    { value: 'person', label: 'Person' },
    { value: 'device', label: 'Device' },
]

const CARD: Record<OverviewTab, () => JSX.Element> = {
    session: QuillOverviewSessionCard,
    person: QuillOverviewPersonCard,
    device: QuillOverviewDeviceCard,
}

export function RecordingOverviewPanels(): JSX.Element {
    const { ref, size } = useResizeBreakpoints({ 0: 'narrow', [WIDE_OVERVIEW_PX]: 'wide' })
    return (
        <div ref={ref} data-attr="watch-panel-overview">
            {size === 'wide' ? <WideOverview /> : <NarrowOverview />}
        </div>
    )
}

function NarrowOverview(): JSX.Element {
    const { overviewTab } = useValues(playerSidebarLogic)
    const { setOverviewTab } = useActions(playerSidebarLogic)
    const Card = CARD[overviewTab]
    return (
        <OverviewFrame>
            <Tabs value={overviewTab} onValueChange={(value) => setOverviewTab(value as OverviewTab)}>
                <TabsList className="w-full">
                    {OVERVIEW_TABS.map((tab) => (
                        <TabsTrigger
                            key={tab.value}
                            value={tab.value}
                            className="flex-1"
                            data-attr={`replay-overview-tab-${tab.value}`}
                        >
                            {tab.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>
            <Card />
            <OverviewExtras />
        </OverviewFrame>
    )
}

function WideOverview(): JSX.Element {
    return (
        <OverviewFrame>
            <div className="grid grid-cols-3 gap-x-2 gap-y-1">
                {OVERVIEW_TABS.map((tab) => {
                    const Card = CARD[tab.value]
                    return (
                        <OverviewColumn key={tab.value} title={tab.label} dataAttr={`watch-overview-${tab.value}`}>
                            <Card />
                        </OverviewColumn>
                    )
                })}
            </div>
            <OverviewExtras />
        </OverviewFrame>
    )
}

function OverviewFrame({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div data-quill className="flex flex-col gap-2 bg-background text-foreground px-2 py-2">
            <QuillTTLWarning />
            {children}
        </div>
    )
}

function OverviewExtras(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { snapshotAt } = useValues(playerMetaLogic(logicProps))
    return (
        <>
            <Collapsible>
                <CollapsibleTrigger className="w-full">
                    Settings at the time of the recording
                    <span className="grow" />
                </CollapsibleTrigger>
                <CollapsibleContent>
                    <QuillSettingsSnapshot at={snapshotAt} scope={OVERVIEW_SNAPSHOT_SCOPE} />
                </CollapsibleContent>
            </Collapsible>
            <QuillExperimentsSection />
            <QuillOverviewOtherWatchers />
        </>
    )
}

function OverviewColumn({
    title,
    dataAttr,
    children,
}: {
    title: string
    dataAttr: string
    children: ReactNode
}): JSX.Element {
    // subgrid keeps the headings, top cards and row tables level across columns
    return (
        <div className="grid grid-cols-1 grid-rows-subgrid row-span-3 gap-1 min-w-0" data-attr={dataAttr}>
            <span className="text-xxs font-semibold uppercase tracking-wide text-muted-foreground px-0.5">{title}</span>
            {children}
        </div>
    )
}
