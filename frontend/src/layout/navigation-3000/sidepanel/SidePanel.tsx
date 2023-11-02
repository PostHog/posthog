import { LemonButton } from '@posthog/lemon-ui'
import './SidePanel.scss'
import { useActions, useValues } from 'kea'
import { SidePanelTab, sidePanelLogic } from './sidePanelLogic'
import clsx from 'clsx'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { useRef } from 'react'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { IconNotebook, IconQuestion, IconInfo } from '@posthog/icons'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'

export const SidePanelTabs: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: NotebookPanel,
    },
    [SidePanelTab.Feedback]: {
        label: 'Feedback',
        Icon: IconQuestion,
        Content: SidePanelSupport,
    },
    [SidePanelTab.Docs]: {
        label: 'Docs',
        Icon: IconInfo,
        Content: SidePanelDocs,
    },
}

export function SidePanel(): JSX.Element | null {
    const { selectedTab, sidePanelOpen, enabledTabs } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelLogic)

    const activeTab = sidePanelOpen && selectedTab

    const PanelConent = activeTab ? SidePanelTabs[activeTab]?.Content : null

    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        persistentKey: 'side-panel',
        closeThreshold: 200,
        placement: 'left',
        onToggleClosed: (shouldBeClosed) => {
            shouldBeClosed ? closeSidePanel() : selectedTab ? openSidePanel(selectedTab) : undefined
        },
    }

    const { desiredWidth, isResizeInProgress } = useValues(resizerLogic(resizerLogicProps))

    if (!enabledTabs.length) {
        return null
    }

    return (
        <div
            className={clsx(
                'SidePanel3000',
                sidePanelOpen && 'SidePanel3000--open',
                isResizeInProgress && 'SidePanel3000--resizing'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: sidePanelOpen ? desiredWidth ?? undefined : undefined,
            }}
        >
            <Resizer {...resizerLogicProps} />
            <div className="SidePanel3000__bar">
                <div className="rotate-90 flex items-center gap-1 px-2">
                    {Object.entries(SidePanelTabs)
                        .filter(([tab]) => enabledTabs.includes(tab as SidePanelTab))
                        .map(([tab, { label, Icon }]) => (
                            <LemonButton
                                key={tab}
                                icon={<Icon className="rotate-270 w-6" />}
                                onClick={() =>
                                    activeTab === tab ? closeSidePanel() : openSidePanel(tab as SidePanelTab)
                                }
                                data-attr={`sidepanel-tab-${tab}`}
                                active={activeTab === tab}
                            >
                                {label}
                            </LemonButton>
                        ))}
                </div>
            </div>
            <Resizer {...resizerLogicProps} offset={'3rem'} />

            {PanelConent ? (
                <div className="SidePanel3000__content">
                    <PanelConent />
                </div>
            ) : null}
        </div>
    )
}
