import { ELEMENT_ANCHOR_LIMITS } from "@posthog/core/comments/anchors";
import type {
  TaskPreviewElement,
  TaskPreviewPin,
  TaskPreviewRect,
} from "@posthog/ui/features/task-preview/taskPreviewFrameHost";
import type {
  TaskPreviewGuestMessage,
  TaskPreviewHostMessage,
} from "../shared/task-preview-message";
import { uniqueSelector } from "./task-preview-selector";

const REPORTED_ATTRIBUTES = [
  "id",
  "class",
  "role",
  "aria-label",
  "data-attr",
  "data-testid",
  "name",
  "type",
  "href",
  "placeholder",
  "title",
  "alt",
];
const PREVIEW_TOKEN_PARAM = "_modal_connect_token";
const PIN_REFRESH_INTERVAL_MS = 500;
const MARKER_RELEASE_TIMEOUT_MS = 4_000;
const MARKER_SIZE = 22;
const ACCENT = "#f54e00";

function truncate(value: string, maxLength: number): string {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
}

function rectOf(element: Element): TaskPreviewRect {
  const rect = element.getBoundingClientRect();
  return {
    top: rect.top,
    left: rect.left,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  };
}

function anchorPoint(element: Element): { top: number; right: number } {
  const range = element.ownerDocument.createRange();
  range.selectNodeContents(element);
  const lines = [...range.getClientRects()].filter(
    (rect) => rect.width > 0 && rect.height > 0,
  );
  if (lines.length === 0) {
    const rect = element.getBoundingClientRect();
    return { top: rect.top, right: rect.right };
  }
  return {
    top: Math.min(...lines.map((rect) => rect.top)),
    right: Math.max(...lines.map((rect) => rect.right)),
  };
}

export function elementText(element: Element): string {
  const text = (element as HTMLElement).innerText ?? element.textContent ?? "";
  return truncate(text.replace(/\s+/g, " ").trim(), ELEMENT_ANCHOR_LIMITS.text);
}

export function previewPath(location: Location): string {
  const params = new URLSearchParams(location.search);
  params.delete(PREVIEW_TOKEN_PARAM);
  const search = params.toString();
  return `${location.pathname}${search ? `?${search}` : ""}${location.hash}`;
}

export function describeElement(element: Element): TaskPreviewElement {
  const attributes: Record<string, string> = {};
  for (const name of REPORTED_ATTRIBUTES) {
    const value = element.getAttribute(name);
    if (value) {
      attributes[name] = truncate(value, ELEMENT_ANCHOR_LIMITS.attributeValue);
    }
  }
  const location = element.ownerDocument.location;
  return {
    path: truncate(
      location ? previewPath(location) : "/",
      ELEMENT_ANCHOR_LIMITS.path,
    ),
    selector: truncate(uniqueSelector(element), ELEMENT_ANCHOR_LIMITS.selector),
    tag: element.tagName.toLowerCase(),
    text: elementText(element),
    html: truncate(element.outerHTML, ELEMENT_ANCHOR_LIMITS.html),
    attributes,
  };
}

function resolvePin(selector: string): Element | null {
  try {
    return document.querySelector(selector);
  } catch {
    return null;
  }
}

export function setupTaskPreviewPicker(
  send: (message: TaskPreviewGuestMessage) => void,
): (message: TaskPreviewHostMessage) => void {
  let overlayRoot: ShadowRoot | null = null;
  let highlight: HTMLDivElement | null = null;
  let pinLayer: HTMLDivElement | null = null;
  let marker: HTMLDivElement | null = null;
  let markedElement: Element | null = null;
  let changedKey = "";
  let releaseTimer: ReturnType<typeof setTimeout> | null = null;
  let picking = false;
  let hovered: Element | null = null;
  let pins: TaskPreviewPin[] = [];
  let refreshTimer: ReturnType<typeof setInterval> | null = null;

  const ensureOverlay = (): ShadowRoot => {
    if (overlayRoot?.host.isConnected) return overlayRoot;
    const host = document.createElement("posthog-preview-overlay");
    host.style.cssText =
      "position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
    overlayRoot = host.attachShadow({ mode: "closed" });
    highlight = document.createElement("div");
    highlight.style.cssText = `position:fixed;display:none;border:2px solid ${ACCENT};background:rgba(245,78,0,0.12);border-radius:2px;pointer-events:none;`;
    pinLayer = document.createElement("div");
    marker = document.createElement("div");
    marker.style.cssText = `position:fixed;display:none;width:${MARKER_SIZE}px;height:${MARKER_SIZE}px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${ACCENT};border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.35);pointer-events:none;`;
    overlayRoot.append(highlight, pinLayer, marker);
    document.documentElement.appendChild(host);
    return overlayRoot;
  };

  const isOverlay = (target: EventTarget | null): boolean =>
    target instanceof Node &&
    !!overlayRoot &&
    (target === overlayRoot.host || overlayRoot.host.contains(target));

  const showHighlight = (element: Element | null) => {
    ensureOverlay();
    if (!highlight) return;
    if (!element) {
      highlight.style.display = "none";
      return;
    }
    const rect = element.getBoundingClientRect();
    highlight.style.display = "block";
    highlight.style.top = `${rect.top}px`;
    highlight.style.left = `${rect.left}px`;
    highlight.style.width = `${rect.width}px`;
    highlight.style.height = `${rect.height}px`;
  };

  const reportChangedPins = (changed: string[]) => {
    const key = changed.join(",");
    if (key === changedKey) return;
    changedKey = key;
    send({ type: "pins-changed", ids: changed });
  };

  const renderPins = () => {
    ensureOverlay();
    if (!pinLayer) return;
    pinLayer.replaceChildren();
    const path = window.location.pathname;
    const changed: string[] = [];
    let markerCovered = false;
    for (const pin of pins) {
      if (pin.path !== path) continue;
      const target = resolvePin(pin.selector);
      if (!target || elementText(target) !== pin.text) changed.push(pin.id);
      if (!target) continue;
      if (target === markedElement) markerCovered = true;
      const rect = target.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;
      const point = anchorPoint(target);
      const badge = document.createElement("button");
      badge.type = "button";
      badge.textContent = String(pin.number);
      badge.setAttribute("aria-label", `Comment ${pin.number}`);
      badge.style.cssText = `position:fixed;top:${Math.max(0, point.top - 10)}px;left:${Math.max(0, point.right - 10)}px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;border:2px solid #fff;background:${pin.active ? "#1d4aff" : ACCENT};color:#fff;font:600 11px/16px system-ui,sans-serif;cursor:pointer;pointer-events:auto;box-shadow:0 1px 3px rgba(0,0,0,0.3);`;
      badge.addEventListener("click", (event) => {
        if (!event.isTrusted) return;
        event.preventDefault();
        event.stopPropagation();
        send({ type: "activate", id: pin.id });
      });
      pinLayer.appendChild(badge);
    }
    if (markerCovered) releaseMarker();
    reportChangedPins(changed);
  };

  let tracked: Element | null = null;
  let trackedKey = "";
  const reportTracked = () => {
    if (!tracked?.isConnected) return;
    const rect = rectOf(tracked);
    const key = `${rect.top},${rect.left},${rect.right},${rect.bottom}`;
    if (key === trackedKey) return;
    trackedKey = key;
    send({ type: "tracked-rect", rect });
  };

  let renderFrame = 0;
  const scheduleRender = () => {
    if (renderFrame) return;
    renderFrame = requestAnimationFrame(() => {
      renderFrame = 0;
      renderPins();
      reportTracked();
    });
  };

  const syncRefreshTimer = () => {
    const needed = pins.length > 0;
    if (needed && !refreshTimer) {
      refreshTimer = setInterval(() => {
        if (document.visibilityState === "visible") renderPins();
      }, PIN_REFRESH_INTERVAL_MS);
    } else if (!needed && refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  };

  const showMarker = (element: Element) => {
    showHighlight(element);
    if (!marker) return;
    markedElement = element;
    const point = anchorPoint(element);
    marker.style.display = "block";
    marker.style.top = `${Math.max(0, point.top - MARKER_SIZE / 2)}px`;
    marker.style.left = `${Math.max(0, point.right - MARKER_SIZE / 2)}px`;
    if (releaseTimer) clearTimeout(releaseTimer);
    releaseTimer = setTimeout(releaseMarker, MARKER_RELEASE_TIMEOUT_MS);
  };

  const releaseMarker = () => {
    if (releaseTimer) clearTimeout(releaseTimer);
    releaseTimer = null;
    markedElement = null;
    if (marker) marker.style.display = "none";
    if (!picking) showHighlight(null);
  };

  const stopPicking = () => {
    picking = false;
    hovered = null;
    showHighlight(null);
    document.documentElement.style.removeProperty("cursor");
  };

  const onMove = (event: MouseEvent) => {
    if (!picking || isOverlay(event.target)) return;
    const target = document.elementFromPoint(event.clientX, event.clientY);
    if (!target || target === hovered) return;
    hovered = target;
    showHighlight(target);
  };

  const swallow = (event: Event) => {
    if (!picking || isOverlay(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
  };

  const onClick = (event: MouseEvent) => {
    if (!picking || isOverlay(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    if (!event.isTrusted) return;
    const target =
      document.elementFromPoint(event.clientX, event.clientY) ?? hovered;
    if (!target) return;
    stopPicking();
    showMarker(target);
    tracked = target;
    trackedKey = "";
    send({
      type: "picked",
      element: describeElement(target),
      rect: rectOf(target),
    });
  };

  const onKey = (event: KeyboardEvent) => {
    if (!picking || event.key !== "Escape") return;
    event.preventDefault();
    stopPicking();
    send({ type: "pick-cancelled" });
  };

  window.addEventListener("mousemove", onMove, true);
  for (const type of ["mousedown", "mouseup", "pointerdown", "pointerup"]) {
    window.addEventListener(type, swallow, true);
  }
  window.addEventListener("click", onClick, true);
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("scroll", scheduleRender, true);
  window.addEventListener("resize", scheduleRender);

  return (message) => {
    if (message.type === "release") {
      releaseMarker();
      return;
    }
    if (message.type === "untrack") {
      tracked = null;
      return;
    }
    if (message.type === "pick") {
      if (message.active) {
        picking = true;
        document.documentElement.style.setProperty("cursor", "crosshair");
      } else {
        stopPicking();
      }
      return;
    }
    if (message.type === "pins") {
      pins = message.items;
      renderPins();
      syncRefreshTimer();
      return;
    }
    const pin = pins.find((item) => item.id === message.id);
    const target = pin ? resolvePin(pin.selector) : null;
    if (!target) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    showHighlight(target);
    setTimeout(() => {
      if (!picking) showHighlight(null);
    }, 1_200);
  };
}
