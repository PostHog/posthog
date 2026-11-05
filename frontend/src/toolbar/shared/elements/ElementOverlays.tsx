import { useActions, useValues } from 'kea'
import { MouseEvent as ReactMouseEvent, ReactNode, useMemo } from 'react'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { useShiftKeyPressed } from 'lib/components/heatmaps/useShiftKeyPressed'

import { AutocaptureElement } from '~/toolbar/shared/elements/AutocaptureElement'
import { AutocaptureElementLabel } from '~/toolbar/shared/elements/AutocaptureElementLabel'
import { elementsLogic } from '~/toolbar/shared/elements/elementsLogic'
import { FocusRect } from '~/toolbar/shared/elements/FocusRect'
import { HeatmapOverlayElements, getStableElementId } from '~/toolbar/shared/elements/HeatmapOverlayElements'
import { heatmapToolbarMenuLogic } from '~/toolbar/shared/elements/heatmapToolbarMenuLogic'
import { ElementHighlight } from '~/toolbar/shared/product-tours/ElementHighlight'
import { getBoxColors, isInToolbarRoot } from '~/toolbar/shared/utils'

import { ScrollDepth } from './ScrollDepth'

const noop = (): void => {}

export function ElementOverlays({
    showHeatmapCanvas,
    children,
}: {
    showHeatmapCanvas: boolean
    /** More highlights, drawn above the area filter and below the element boxes. */
    children?: ReactNode
}): JSX.Element {
    const {
        heatmapElements,
        elementsToDisplay,
        labelsToDisplay,
        hoverElement,
        selectedElement,
        inspectEnabled,
        highlightElementMeta,
        relativePositionCompensation,
        heatmapEnabled,
        rectUpdateCounter,
    } = useValues(elementsLogic)
    const { setHoverElement, selectElement } = useActions(elementsLogic)
    const { highestClickCount, areaSelectionActive, areaHoverElement, heatmapAreaFilter, areaCandidates } =
        useValues(heatmapToolbarMenuLogic)
    const { refreshClickmap, setAreaHover, selectHeatmapAreaFilter } = useActions(heatmapToolbarMenuLogic)

    const shiftPressed = useShiftKeyPressed(refreshClickmap)
    // while picking an area the page itself must receive pointer events, so all overlays pass through
    const heatmapPointerEvents = shiftPressed || areaSelectionActive ? 'none' : 'all'

    // recomputed on scroll/resize via rectUpdateCounter so the fixed-position highlights track the page
    const areaHoverRect = useMemo(
        () => (areaHoverElement?.isConnected ? areaHoverElement.getBoundingClientRect() : null),
        [areaHoverElement, rectUpdateCounter] // eslint-disable-line react-hooks/exhaustive-deps
    )
    const areaFilterRect = useMemo(
        () => (heatmapAreaFilter?.element.isConnected ? heatmapAreaFilter.element.getBoundingClientRect() : null),
        [heatmapAreaFilter, rectUpdateCounter] // eslint-disable-line react-hooks/exhaustive-deps
    )
    // already sorted biggest-first, so nested candidates paint children-on-top and stay hoverable
    const areaCandidateRects = useMemo(
        () =>
            areaSelectionActive
                ? areaCandidates
                      .filter((element) => element.isConnected)
                      .map((element) => ({ element, rect: element.getBoundingClientRect() }))
                : [],
        [areaSelectionActive, areaCandidates, rectUpdateCounter] // eslint-disable-line react-hooks/exhaustive-deps
    )

    const hoverAreaCandidate = (e: ReactMouseEvent, element: HTMLElement): void => {
        // the real page leaf under the pointer (not this overlay box) anchors the arrow-key
        // walk, so pressing down still shrinks toward what the user is pointing at
        const leaf = (document.elementsFromPoint(e.clientX, e.clientY) as HTMLElement[]).find(
            (el) => !isInToolbarRoot(el)
        )
        setAreaHover(leaf ?? element, element)
    }

    return (
        <div
            id="posthog-toolbar-elements"
            className="w-full h-full absolute top-0 pointer-events-none z-[2147483010]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: relativePositionCompensation,
            }}
        >
            <ScrollDepth />
            {showHeatmapCanvas && <HeatmapCanvas positioning="absolute" context="toolbar" />}
            {highlightElementMeta?.rect ? <FocusRect rect={highlightElementMeta.rect} /> : null}
            {areaCandidateRects.map(({ element, rect }) => (
                <AutocaptureElement
                    key={`area-candidate-${getStableElementId(element)}`}
                    rect={rect}
                    style={{
                        pointerEvents: 'all',
                        cursor: 'crosshair',
                        zIndex: 1,
                        borderRadius: 5,
                        opacity: !areaHoverElement || areaHoverElement === element ? 1 : 0.6,
                        transition: 'opacity 0.2s, box-shadow 0.2s',
                        ...getBoxColors('blue', areaHoverElement === element, 0.1),
                    }}
                    onMouseOver={(e) => hoverAreaCandidate(e, element)}
                    onMouseOut={noop}
                    onClick={() => selectHeatmapAreaFilter(areaHoverElement ?? element)}
                />
            ))}
            {areaSelectionActive && areaHoverRect && <ElementHighlight rect={areaHoverRect} />}
            {heatmapEnabled && !areaSelectionActive && areaFilterRect && (
                <ElementHighlight rect={areaFilterRect} isSelected />
            )}
            {children}

            {elementsToDisplay.map(({ rect, element, apparentZIndex }) => {
                return (
                    <AutocaptureElement
                        key={`inspect-${getStableElementId(element)}`}
                        rect={rect}
                        style={{
                            pointerEvents: heatmapPointerEvents,
                            cursor: 'pointer',
                            zIndex: apparentZIndex ? apparentZIndex : hoverElement === element ? 2 : 1,
                            opacity:
                                (!hoverElement && !selectedElement) ||
                                selectedElement === element ||
                                hoverElement === element
                                    ? 1
                                    : 0.4,
                            transition: 'opacity 0.2s, box-shadow 0.2s',
                            borderRadius: 5,
                            ...getBoxColors('blue', hoverElement === element || selectedElement === element),
                        }}
                        onClick={() => selectElement(element)}
                        onMouseOver={() => selectedElement === null && setHoverElement(element)}
                        onMouseOut={() => selectedElement === null && setHoverElement(null)}
                    />
                )
            })}

            <HeatmapOverlayElements
                heatmapElements={heatmapElements}
                hoverElement={hoverElement}
                selectedElement={selectedElement}
                inspectEnabled={inspectEnabled}
                heatmapPointerEvents={heatmapPointerEvents}
                highestClickCount={highestClickCount}
                selectElement={selectElement}
                setHoverElement={setHoverElement}
            />

            {labelsToDisplay.map(({ element, rect, index, visible }, loopIndex) => {
                if (!visible || !rect) {
                    return null
                }
                return (
                    <AutocaptureElementLabel
                        key={`label-${getStableElementId(element)}`}
                        rect={rect}
                        align="left"
                        style={{
                            zIndex: 5,
                            opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                            transition: 'opacity 0.2s, transform 0.2s linear',
                            transform: hoverElement === element ? 'scale(1.3)' : 'none',
                            pointerEvents: heatmapPointerEvents,
                            cursor: 'pointer',
                            color: 'hsla(141, 21%, 12%, 1)',
                            background: 'hsl(147, 100%, 62%)',
                            boxShadow: 'hsla(141, 100%, 32%, 1) 0px 1px 5px 1px',
                        }}
                        onClick={() => selectElement(element)}
                        onMouseOver={() => selectedElement === null && setHoverElement(element)}
                        onMouseOut={() => selectedElement === null && setHoverElement(null)}
                    >
                        {(index || loopIndex) + 1}
                    </AutocaptureElementLabel>
                )
            })}
        </div>
    )
}
