import { LemonButton } from '@posthog/lemon-ui'
import './SidePanel.scss'
import { useActions, useValues } from 'kea'
import { SidePanelTab, SidePanelTabs, sidePanelLogic } from './sidePanelLogic'
import clsx from 'clsx'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { useRef } from 'react'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

export function SidePanel(): JSX.Element {
    const { selectedTab, sidePanelOpen } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelLogic)

    const activeTab = sidePanelOpen && selectedTab

    const PanelConent = activeTab ? SidePanelTabs[activeTab]?.Content : null

    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        persistentKey: '',
        closeThreshold: 450,
        onToggleClosed: (shouldBeClosed) => {
            shouldBeClosed ? closeSidePanel() : selectedTab ? openSidePanel(selectedTab) : undefined
        },
    }

    const { desiredWidth } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            className={clsx('SidePanel3000', sidePanelOpen && 'SidePanel3000--open')}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: sidePanelOpen ? desiredWidth ?? undefined : undefined,
            }}
        >
            <Resizer {...resizerLogicProps} />
            <div className="SidePanel3000__bar">
                <div className="rotate-90 flex items-center gap-2 px-2">
                    {Object.entries(SidePanelTabs).map(([tab, { label, Icon }]) => (
                        <LemonButton
                            key={tab}
                            icon={<Icon className="rotate-270 w-6" />}
                            onClick={() => (activeTab === tab ? closeSidePanel() : openSidePanel(tab as SidePanelTab))}
                            data-attr={`sidepanel-tab-${tab}`}
                            active={activeTab === tab}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </div>
            </div>

            {PanelConent ? (
                <div className="SidePanel3000__content">
                    <PanelConent />
                </div>
            ) : null}
        </div>
    )
}
