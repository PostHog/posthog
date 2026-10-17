import './SidePanel.scss'

import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { cn } from 'lib/utils/css-classes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { SidePanelContent } from './SidePanelContent'
import { sidePanelStateLogic } from './sidePanelStateLogic'
import { SIDE_PANEL_TABS } from './sidePanelTabs'
import { SIDE_PANEL_MIN_WIDTH_COMPACT, useSidePanelFrame } from './useSidePanelFrame'

const DEFAULT_WIDTH = 512

export const SidePanel = memo(function SidePanel({ className }: { className?: string }): JSX.Element | null {
    const { theme } = useValues(themeLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { ref, resizerLogicProps, isResizeInProgress, activeTab, width, hasTabs } = useSidePanelFrame({
        defaultWidth: DEFAULT_WIDTH,
    })
    const PanelContent = activeTab ? SIDE_PANEL_TABS[activeTab]?.Content : null

    if (!hasTabs) {
        return null
    }

    return (
        <div
            className={cn(
                'SidePanel3000',
                activeTab && 'SidePanel3000--open justify-end',
                isResizeInProgress && 'SidePanel3000--resizing',
                '@container/side-panel bg-surface-secondary absolute top-0 right-0 bottom-0 h-full flex flex-col border-t-none',
                '[--side-panel-width:initial] [--scene-layout-rect-width:initial] [--scene-layout-rect-right:initial]',
                !sidePanelOpen && 'hidden',
                className
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    width: activeTab ? width : '0px',
                    '--side-panel-min-width': `${SIDE_PANEL_MIN_WIDTH_COMPACT}px`,
                    ...theme?.sidebarStyle,
                } as React.CSSProperties
            }
            id="side-panel"
        >
            {activeTab && (
                <>
                    <Resizer
                        {...resizerLogicProps}
                        className={cn('top-[calc(var(--scene-layout-header-height)+8px)] left-[-1px] bottom-4', {
                            'left-0': !!activeTab,
                            'top-0 h-full': !!activeTab,
                        })}
                    />
                    {/* Overlay for mobile to click outside to close the side panel */}
                    <div onClick={() => closeSidePanel()} className="lg:hidden fixed inset-0 -z-1" />
                </>
            )}

            {activeTab && PanelContent && <SidePanelContent activeTab={activeTab} Content={PanelContent} />}
        </div>
    )
})
