import { useActions, useValues } from "kea";
import { Fragment, memo, useRef } from "react";

import { HeatmapCanvas } from "lib/components/heatmaps/HeatmapCanvas";
import { useShiftKeyPressed } from "lib/components/heatmaps/useShiftKeyPressed";
import { compactNumber } from "lib/utils";

import { AutocaptureElement } from "~/toolbar/elements/AutocaptureElement";
import { AutocaptureElementLabel } from "~/toolbar/elements/AutocaptureElementLabel";
import { ElementInfoWindow } from "~/toolbar/elements/ElementInfoWindow";
import { elementsLogic } from "~/toolbar/elements/elementsLogic";
import { FocusRect } from "~/toolbar/elements/FocusRect";
import { heatmapToolbarMenuLogic } from "~/toolbar/elements/heatmapToolbarMenuLogic";
import { ElementHighlight } from "~/toolbar/product-tours/ElementHighlight";
import { productToursLogic } from "~/toolbar/product-tours/productToursLogic";
import { ElementWithMetadata } from "~/toolbar/types";
import { getBoxColors, getHeatMapHue } from "~/toolbar/utils";

import { toolbarLogic } from "../bar/toolbarLogic";
import { ScrollDepth } from "./ScrollDepth";

function useStableElementId(): (el: HTMLElement) => number {
  const mapRef = useRef(new WeakMap<HTMLElement, number>());
  const counterRef = useRef(0);
  return (el: HTMLElement): number => {
    let id = mapRef.current.get(el);
    if (id === undefined) {
      id = counterRef.current++;
      mapRef.current.set(el, id);
    }
    return id;
  };
}

export function Elements(): JSX.Element {
  const { visibleMenu: activeToolbarMode } = useValues(toolbarLogic);
  const {
    heatmapElements,
    elementsToDisplay,
    labelsToDisplay,
    hoverElement,
    selectedElement,
    inspectEnabled,
    highlightElementMeta,
    relativePositionCompensation,
  } = useValues(elementsLogic);
  const { setHoverElement, selectElement } = useActions(elementsLogic);
  const { highestClickCount } = useValues(heatmapToolbarMenuLogic);
  const { refreshClickmap } = useActions(heatmapToolbarMenuLogic);
  const {
    isSelecting: productToursSelecting,
    hoverElementRect: productToursHoverRect,
    expandedStepRect: productToursSelectedStepRect,
  } = useValues(productToursLogic);

  const getStableId = useStableElementId();

  const shiftPressed = useShiftKeyPressed(refreshClickmap);
  const heatmapPointerEvents = shiftPressed ? "none" : "all";

  const { theme } = useValues(toolbarLogic);

  // KLUDGE: if we put theme directly on the div then
  // linting and typescript complain about it not being
  // a valid attribute. So we put it in a variable and
  // spread it in. 🤷‍
  const themeProps = { theme };

  return (
    <>
      <div
        id="posthog-infowindow-container"
        className="w-full h-full absolute top-0 left-0 pointer-events-none z-[2147483021]"
        {...themeProps}
      >
        <ElementInfoWindow />
      </div>

      <div
        id="posthog-toolbar-elements"
        className="w-full h-full absolute top-0 pointer-events-none z-[2147483010]"
        // eslint-disable-next-line react/forbid-dom-props
        style={{
          top: relativePositionCompensation,
        }}
      >
        <ScrollDepth />
        {activeToolbarMode === "heatmap" && (
          <HeatmapCanvas positioning="absolute" context="toolbar" />
        )}
        {highlightElementMeta?.rect ? (
          <FocusRect rect={highlightElementMeta.rect} />
        ) : null}
        {productToursSelecting && productToursHoverRect && (
          <ElementHighlight rect={productToursHoverRect} />
        )}
        {productToursSelectedStepRect && (
          <ElementHighlight rect={productToursSelectedStepRect} isSelected />
        )}

        {elementsToDisplay.map(({ rect, element, apparentZIndex }) => {
          return (
            <AutocaptureElement
              key={`inspect-${getStableId(element)}`}
              rect={rect}
              style={{
                pointerEvents: heatmapPointerEvents,
                cursor: "pointer",
                zIndex: apparentZIndex
                  ? apparentZIndex
                  : hoverElement === element
                    ? 2
                    : 1,
                opacity:
                  (!hoverElement && !selectedElement) ||
                  selectedElement === element ||
                  hoverElement === element
                    ? 1
                    : 0.4,
                transition: "opacity 0.2s, box-shadow 0.2s",
                borderRadius: 5,
                ...getBoxColors(
                  "blue",
                  hoverElement === element || selectedElement === element,
                ),
              }}
              onClick={() => selectElement(element)}
              onMouseOver={() =>
                selectedElement === null && setHoverElement(element)
              }
              onMouseOut={() =>
                selectedElement === null && setHoverElement(null)
              }
            />
          );
        })}

        <HeatmapOverlayElements
          heatmapElements={heatmapElements}
          highestClickCount={highestClickCount}
          hoverElement={hoverElement}
          selectedElement={selectedElement}
          inspectEnabled={inspectEnabled}
          heatmapPointerEvents={heatmapPointerEvents}
          selectElement={selectElement}
          setHoverElement={setHoverElement}
          getStableId={getStableId}
        />

        {labelsToDisplay.map(({ element, rect, index, visible }) => {
          if (!visible || !rect) {
            return null;
          }
          return (
            <AutocaptureElementLabel
              key={`label-${getStableId(element)}`}
              rect={rect}
              align="left"
              style={{
                zIndex: 5,
                opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                transition: "opacity 0.2s, transform 0.2s linear",
                transform: hoverElement === element ? "scale(1.3)" : "none",
                pointerEvents: heatmapPointerEvents,
                cursor: "pointer",
                color: "hsla(141, 21%, 12%, 1)",
                background: "hsl(147, 100%, 62%)",
                boxShadow: "hsla(141, 100%, 32%, 1) 0px 1px 5px 1px",
              }}
              onClick={() => selectElement(element)}
              onMouseOver={() =>
                selectedElement === null && setHoverElement(element)
              }
              onMouseOut={() =>
                selectedElement === null && setHoverElement(null)
              }
            >
              {(index ?? 0) + 1}
            </AutocaptureElementLabel>
          );
        })}
      </div>
    </>
  );
}

interface HeatmapOverlayElementsProps {
  heatmapElements: ElementWithMetadata[];
  highestClickCount: number;
  hoverElement: HTMLElement | null;
  selectedElement: HTMLElement | null;
  inspectEnabled: boolean;
  heatmapPointerEvents: string;
  selectElement: (element: HTMLElement) => void;
  setHoverElement: (element: HTMLElement | null) => void;
  getStableId: (el: HTMLElement) => number;
}

const HeatmapOverlayElements = memo(function HeatmapOverlayElements({
  heatmapElements,
  highestClickCount,
  hoverElement,
  selectedElement,
  inspectEnabled,
  heatmapPointerEvents,
  selectElement,
  setHoverElement,
  getStableId,
}: HeatmapOverlayElementsProps): JSX.Element {
  return (
    <>
      {heatmapElements.map(
        ({
          rect,
          count,
          clickCount,
          rageclickCount,
          deadclickCount,
          element,
          visible,
        }) => {
          if (!visible) {
            return null;
          }
          const stableId = getStableId(element);
          return (
            <Fragment key={`heatmap-${stableId}`}>
              <AutocaptureElement
                rect={rect}
                style={{
                  pointerEvents: inspectEnabled ? "none" : heatmapPointerEvents,
                  zIndex: hoverElement === element ? 4 : 3,
                  opacity: !hoverElement || hoverElement === element ? 1 : 0.4,
                  transition: "opacity 0.2s, box-shadow 0.2s",
                  cursor: "pointer",
                  borderRadius: 5,
                  ...getBoxColors(
                    "red",
                    hoverElement === element,
                    ((count || 0) / highestClickCount) * 0.4,
                  ),
                }}
                onClick={() => selectElement(element)}
                onMouseOver={() =>
                  selectedElement === null && setHoverElement(element)
                }
                onMouseOut={() =>
                  selectedElement === null && setHoverElement(null)
                }
              />
              {!!clickCount && (
                <AutocaptureElementLabel
                  rect={rect}
                  style={{
                    pointerEvents: heatmapPointerEvents,
                    zIndex: 5,
                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                    transition: "opacity 0.2s, transform 0.2s linear",
                    transform: hoverElement === element ? "scale(1.3)" : "none",
                    cursor: "pointer",
                    color: `hsla(${getHeatMapHue(clickCount || 0, highestClickCount)}, 20%, 12%, 1)`,
                    background: `hsla(${getHeatMapHue(clickCount || 0, highestClickCount)}, 100%, 62%, 1)`,
                    boxShadow: `hsla(${getHeatMapHue(clickCount || 0, highestClickCount)}, 100%, 32%, 1) 0px 1px 5px 1px`,
                  }}
                  onClick={() => selectElement(element)}
                  onMouseOver={() =>
                    selectedElement === null && setHoverElement(element)
                  }
                  onMouseOut={() =>
                    selectedElement === null && setHoverElement(null)
                  }
                >
                  {compactNumber(clickCount || 0)}
                </AutocaptureElementLabel>
              )}
              {!!rageclickCount && (
                <AutocaptureElementLabel
                  rect={rect}
                  style={{
                    pointerEvents: heatmapPointerEvents,
                    zIndex: 5,
                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                    transition: "opacity 0.2s, transform 0.2s linear",
                    transform: hoverElement === element ? "scale(1.3)" : "none",
                    cursor: "pointer",
                    color: `hsla(${getHeatMapHue(rageclickCount || 0, highestClickCount)}, 20%, 12%, 1)`,
                    background: `hsla(${getHeatMapHue(rageclickCount || 0, highestClickCount)}, 100%, 62%, 1)`,
                    boxShadow: `hsla(${getHeatMapHue(rageclickCount || 0, highestClickCount)}, 100%, 32%, 1) 0px 1px 5px 1px`,
                  }}
                  align="left"
                  onClick={() => selectElement(element)}
                  onMouseOver={() =>
                    selectedElement === null && setHoverElement(element)
                  }
                  onMouseOut={() =>
                    selectedElement === null && setHoverElement(null)
                  }
                >
                  {compactNumber(rageclickCount)}&#128545;
                </AutocaptureElementLabel>
              )}
              {!!deadclickCount && (
                <AutocaptureElementLabel
                  rect={rect}
                  style={{
                    pointerEvents: heatmapPointerEvents,
                    zIndex: 5,
                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                    transition: "opacity 0.2s, transform 0.2s linear",
                    transform: hoverElement === element ? "scale(1.3)" : "none",
                    cursor: "pointer",
                    color: `hsla(${getHeatMapHue(deadclickCount || 0, highestClickCount)}, 20%, 12%, 1)`,
                    background: `hsla(${getHeatMapHue(deadclickCount || 0, highestClickCount)}, 100%, 62%, 1)`,
                    boxShadow: `hsla(${getHeatMapHue(deadclickCount || 0, highestClickCount)}, 100%, 32%, 1) 0px 1px 5px 1px`,
                  }}
                  align="left"
                  onClick={() => selectElement(element)}
                  onMouseOver={() =>
                    selectedElement === null && setHoverElement(element)
                  }
                  onMouseOut={() =>
                    selectedElement === null && setHoverElement(null)
                  }
                >
                  {compactNumber(deadclickCount)}&#128565;
                </AutocaptureElementLabel>
              )}
            </Fragment>
          );
        },
      )}
    </>
  );
});
