import { useValues } from 'kea'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { cn } from 'lib/utils/css-classes'

import { SIDE_PANEL_MIN_WIDTH_COMPACT, useSidePanelFrame } from '~/layout/navigation-3000/sidepanel/useSidePanelFrame'

import { TodayContextPanelCard } from './TodayContextPanelCard'
import { TODAY_SIDE_PANEL_DEFAULT_WIDTH } from './todayContextPanelLogic'
import { todayShellLogic } from './todayShellLogic'

// The Today layout gives the panel its own grid column, so a wider panel takes the space from the scene.
const TODAY_SIDE_PANEL_MAX_WIDTH = 720
// The scene keeps at least this much width beside a wide panel, so a narrow window never collapses it.
const TODAY_SCENE_MIN_WIDTH = 320

export function TodaySidePanel(): JSX.Element | null {
    const { leftNavWidth } = useValues(todayShellLogic)
    const { windowSize } = useWindowSize()
    const roomBesideNav = windowSize.width != null ? windowSize.width - leftNavWidth - TODAY_SCENE_MIN_WIDTH : Infinity
    const { ref, resizerLogicProps, isResizeInProgress, activeTab, width, hasTabs } = useSidePanelFrame({
        defaultWidth: TODAY_SIDE_PANEL_DEFAULT_WIDTH,
        // Never below the panel's own minimum: in a very narrow window the scene gives up the width instead.
        maxWidth: Math.max(SIDE_PANEL_MIN_WIDTH_COMPACT, Math.min(TODAY_SIDE_PANEL_MAX_WIDTH, roomBesideNav)),
    })

    if (!hasTabs) {
        return null
    }

    return (
        <div
            className={cn(
                'TodayAppLayout__side-panel @container/side-panel relative flex h-full min-h-0 flex-col px-1 pb-1',
                '[--side-panel-width:initial] [--scene-layout-rect-width:initial] [--scene-layout-rect-right:initial]',
                isResizeInProgress && 'pointer-events-none',
                !activeTab && 'hidden'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width }}
            id="side-panel"
        >
            {activeTab && (
                <>
                    <Resizer {...resizerLogicProps} visible={false} className="left-0 top-0 h-full" />
                    <TodayContextPanelCard docked tab={activeTab} className="h-full" />
                </>
            )}
        </div>
    )
}
