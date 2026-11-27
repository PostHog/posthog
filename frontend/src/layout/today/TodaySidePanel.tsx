import { useActions, useValues } from 'kea'

import { useWindowSize } from 'lib/hooks/useWindowSize'
import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'

import { SIDE_PANEL_MIN_WIDTH_COMPACT, useSidePanelFrame } from '~/layout/navigation-3000/sidepanel/useSidePanelFrame'

import { TodayContextPanelCard } from './TodayContextPanelCard'
import { TODAY_SIDE_PANEL_DEFAULT_WIDTH } from './todayContextPanelLogic'
import { todayShellLogic } from './todayShellLogic'

// Up to this width the panel pushes the scene aside. Wider, it covers the scene, which keeps its width and doesn't
// reflow. Half of the people who resize the panel stop below this.
const TODAY_SIDE_PANEL_PUSH_MAX_WIDTH = 560
// The scene keeps at least this much width beside a pushing panel, so a narrow window never collapses it.
const TODAY_SCENE_MIN_WIDTH = 320
// A covering panel always leaves this much of the scene showing, so there is scene left to click.
const TODAY_SCENE_PEEK_WIDTH = 50

export function TodaySidePanel(): JSX.Element | null {
    const { leftNavWidth } = useValues(todayShellLogic)
    const { windowSize } = useWindowSize()
    const rowWidth = windowSize.width != null ? windowSize.width - leftNavWidth : Infinity
    const { ref, resizerLogicProps, isResizeInProgress, activeTab, width, pushWidth, hasTabs } = useSidePanelFrame({
        defaultWidth: TODAY_SIDE_PANEL_DEFAULT_WIDTH,
        // Never below the panel's own minimum: in a very narrow window the scene gives up the width instead.
        maxWidth: Math.max(SIDE_PANEL_MIN_WIDTH_COMPACT, rowWidth - TODAY_SCENE_PEEK_WIDTH),
        pushMaxWidth: Math.max(
            SIDE_PANEL_MIN_WIDTH_COMPACT,
            Math.min(TODAY_SIDE_PANEL_PUSH_MAX_WIDTH, rowWidth - TODAY_SCENE_MIN_WIDTH)
        ),
    })
    const { setDesiredSize } = useActions(resizerLogic(resizerLogicProps))
    const covering = !!activeTab && width > pushWidth

    if (!hasTabs) {
        return null
    }

    return (
        // The grid cell only holds the pushed width. The panel inside is pinned to its right edge and grows left from
        // there, over the scene once it is wider than the cell.
        <div
            className={cn(
                // Above the scene's frame border, which would otherwise draw over a covering panel.
                'TodayAppLayout__side-panel relative z-[calc(var(--z-layout-navbar-under)+1)] h-full min-h-0',
                '[--side-panel-width:initial] [--scene-layout-rect-width:initial] [--scene-layout-rect-right:initial]',
                isResizeInProgress && 'pointer-events-none',
                !activeTab && 'hidden'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: pushWidth }}
            id="side-panel"
        >
            {/* A covered scene steps back, and a click on it narrows the panel to where it pushes again. Out of the
                tab order: the panel's resizer does the same for the keyboard. */}
            <button
                type="button"
                aria-hidden
                tabIndex={-1}
                className={cn(
                    'absolute inset-y-0 right-0 cursor-default border-0 bg-black/50 p-0 transition-opacity duration-200 ease-out motion-reduce:transition-none',
                    covering ? 'opacity-100' : 'pointer-events-none opacity-0'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: rowWidth }}
                onClick={() => setDesiredSize(pushWidth)}
            />
            <div
                ref={ref}
                className="@container/side-panel absolute inset-y-0 right-0 flex min-h-0 flex-col px-1 pb-1"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width }}
            >
                {activeTab && (
                    <>
                        <Resizer {...resizerLogicProps} visible={false} className="left-0 top-0 h-full" />
                        <TodayContextPanelCard docked tab={activeTab} className="h-full" />
                    </>
                )}
            </div>
        </div>
    )
}
