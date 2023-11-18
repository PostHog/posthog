import { LemonButton } from '@posthog/lemon-ui'
import './SidePanel.scss'
import { useActions, useValues } from 'kea'
import { sidePanelLogic } from './sidePanelLogic'
import clsx from 'clsx'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { useRef } from 'react'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { IconNotebook, IconInfo, IconSupport, IconGear } from '@posthog/icons'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { NotebookPanel } from 'scenes/notebooks/NotebookPanel/NotebookPanel'
import { SidePanelActivation, SidePanelActivationIcon } from './panels/SidePanelActivation'
import { SidePanelSettings } from './panels/SidePanelSettings'
import { SidePanelTab } from '~/types'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SidePanelTabs: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: NotebookPanel,
    },
    [SidePanelTab.Support]: {
        label: 'Support',
        Icon: IconSupport,
        Content: SidePanelSupport,
    },
    [SidePanelTab.Docs]: {
        label: 'Docs',
        Icon: IconInfo,
        Content: SidePanelDocs,
    },

    [SidePanelTab.Activation]: {
        label: 'Quick start',
        Icon: SidePanelActivationIcon,
        Content: SidePanelActivation,
    },
    [SidePanelTab.Settings]: {
        label: 'Settings',
        Icon: IconGear,
        Content: SidePanelSettings,
    },
}

export function SidePanel(): JSX.Element | null {
    const { visibleTabs } = useValues(sidePanelLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)

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

    if (!visibleTabs.length) {
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
                    {visibleTabs.map((tab: SidePanelTab) => {
                        const { Icon, label } = SidePanelTabs[tab]
                        return (
                            <LemonButton
                                key={tab}
                                icon={<Icon className="rotate-270 w-6" />}
                                onClick={() =>
                                    activeTab === tab ? closeSidePanel() : openSidePanel(tab as SidePanelTab)
                                }
                                data-attr={`sidepanel-tab-${tab}`}
                                active={activeTab === tab}
                                type="secondary"
                                stealth={true}
                            >
                                {label}
                            </LemonButton>
                        )
                    })}
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
