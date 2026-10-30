import { useActions } from 'kea'

import { ResizeGrip, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

/**
 * A resize grip centered on a popup's end edge, which `resizerLogic` drags and keeps. Pass it as the popup's
 * `popupSibling`, so the popup's overflow does not clip it. Double-clicking resets the size.
 */
export function TodayPopupResizeHandle({ resizerProps }: { resizerProps: ResizerLogicProps }): JSX.Element {
    const { beginResize } = useActions(resizerLogic(resizerProps))
    return (
        // The tooltip follows the pointer along the edge, so it stays beside the spot the user is about to drag.
        <Tooltip trackCursorAxis="y">
            <TooltipTrigger
                delay={0}
                render={
                    <ResizeGrip
                        aria-label="Resize menu"
                        // The popup's border is the line, so only the pill shows, centered on that border.
                        className="absolute inset-y-0 end-0 z-10 translate-x-1/2 bg-transparent [--quill-resizable-hit-size:0.5rem] rtl:-translate-x-1/2"
                        data-attr="today-popup-resize"
                        onMouseDown={(event) => {
                            if (event.button === 0) {
                                event.preventDefault()
                                beginResize(event.pageX)
                            }
                        }}
                    />
                }
            />
            <TooltipContent side="right">Drag to resize. Double-click to reset.</TooltipContent>
        </Tooltip>
    )
}
