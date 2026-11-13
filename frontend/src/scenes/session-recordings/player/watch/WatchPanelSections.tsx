import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { IconBug, IconInfo, IconSidePanel, IconSparkles } from '@posthog/icons'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Badge, Button } from '@posthog/quill'

import { WatchPanelSection, playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'
import { PlayerSidebarTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarTab'
import { useLinkedIssuesAvailable } from 'scenes/session-recordings/player/sidebar/useLinkedIssuesAvailable'

import { SessionRecordingSidebarTab } from '~/types'

import { DebugTabBar, debugTabKeys } from './DebugTabBar'
import { RecordingOverviewPanels } from './RecordingOverviewPanels'

const ITEM_CLASS = '[&>h3]:m-0 [&>h3]:font-[inherit]'

export interface ObservationsSection {
    count: number
    hasObservations: boolean
    content: ReactNode
    action?: ReactNode
}

export function WatchPanelSections({
    observations,
    debug,
}: {
    observations?: ObservationsSection
    debug: boolean
}): JSX.Element {
    const { watchPanelOpenSections, watchPanelFocusRequest } = useValues(playerSettingsLogic)
    const { setWatchPanelOpenSections, openWatchPanelSection, setWatchDebugDock, clearWatchPanelFocus } =
        useActions(playerSettingsLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const linkedIssuesAvailable = useLinkedIssuesAvailable()

    const shown: WatchPanelSection[] = [
        'overview',
        ...(observations ? (['observations'] as const) : []),
        ...(debug ? (['debug'] as const) : []),
    ]
    const stored = watchPanelOpenSections[watchPanelOpenSections.length - 1]
    const fallback: WatchPanelSection = observations ? 'observations' : 'overview'
    const open: WatchPanelSection[] = stored ? [shown.includes(stored) ? stored : fallback] : []
    const onOpenChange = (value: unknown[]): void => {
        const [opened] = value as WatchPanelSection[]
        if (opened) {
            openWatchPanelSection(opened)
        } else {
            setWatchPanelOpenSections([])
        }
    }

    const debugTabs = debugTabKeys(linkedIssuesAvailable)
    const debugTab = debugTabs.includes(activeTab) ? activeTab : SessionRecordingSidebarTab.INSPECTOR

    const itemRefs = useRef<Partial<Record<WatchPanelSection, HTMLDivElement | null>>>({})
    useEffect(() => {
        if (!watchPanelFocusRequest) {
            return
        }
        itemRefs.current[watchPanelFocusRequest.section]?.scrollIntoView({ block: 'start' })
        clearWatchPanelFocus()
    }, [watchPanelFocusRequest, clearWatchPanelFocus])

    return (
        <Accordion value={open} onValueChange={onOpenChange} data-attr="watch-panel-sections">
            <AccordionItem
                value="overview"
                className={ITEM_CLASS}
                ref={(el) => {
                    itemRefs.current.overview = el
                }}
            >
                <AccordionTrigger data-attr="watch-panel-section-overview">
                    <span className="flex items-center gap-1.5">
                        <IconInfo />
                        Overview
                    </span>
                </AccordionTrigger>
                <AccordionContent className="-mx-2">
                    <RecordingOverviewPanels />
                </AccordionContent>
            </AccordionItem>
            {observations && (
                <AccordionItem
                    value="observations"
                    ref={(el) => {
                        itemRefs.current.observations = el
                    }}
                >
                    {/* Subgrid puts the action between the trigger's label and chevron. */}
                    <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center [&>h3]:col-span-full [&>h3]:row-start-1 [&>h3]:grid [&>h3]:grid-cols-subgrid [&>h3]:m-0 [&>h3]:font-[inherit]">
                        <AccordionTrigger
                            className="col-span-full grid grid-cols-subgrid items-center gap-0 [&>span]:min-w-0 [&>svg]:col-start-3"
                            data-attr="watch-panel-section-observations"
                        >
                            <span className="flex items-center gap-1.5 min-w-0">
                                <IconSparkles className="shrink-0" />
                                <span className="truncate">Replay Vision observations</span>
                                {observations.count > 0 && <Badge className="shrink-0">{observations.count}</Badge>}
                            </span>
                        </AccordionTrigger>
                        {observations.action && (
                            <div className="relative col-start-2 row-start-1 px-2">{observations.action}</div>
                        )}
                    </div>
                    <AccordionContent>{observations.content}</AccordionContent>
                </AccordionItem>
            )}
            {debug && (
                <AccordionItem
                    value="debug"
                    className={ITEM_CLASS}
                    ref={(el) => {
                        itemRefs.current.debug = el
                    }}
                >
                    <AccordionTrigger data-attr="watch-panel-section-debug">
                        <span className="flex items-center gap-1.5">
                            <IconBug />
                            Debug
                        </span>
                    </AccordionTrigger>
                    <AccordionContent className="-mx-2 pb-0">
                        <div
                            data-not-quill
                            className="SessionRecordingPlayerWrapper__dock-in flex flex-col min-w-0 overflow-hidden h-[calc(45cqh-1.5rem)] min-h-48"
                            data-attr="watch-panel-debug"
                        >
                            <DebugTabBar tabs={debugTabs} activeTab={debugTab} onChange={setTab}>
                                <Button
                                    size="icon"
                                    onClick={() => setWatchDebugDock('right')}
                                    tooltip="Dock to right"
                                    aria-label="Dock to right"
                                    className="rounded-none"
                                    data-attr="player-sidebar-dock-toggle"
                                >
                                    <IconSidePanel />
                                </Button>
                            </DebugTabBar>
                            <PlayerSidebarTab tab={debugTab} />
                        </div>
                    </AccordionContent>
                </AccordionItem>
            )}
        </Accordion>
    )
}
