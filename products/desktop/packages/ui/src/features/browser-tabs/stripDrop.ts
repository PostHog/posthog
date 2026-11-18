export const STRIP_DROP_TYPE = "tab-strip";

export interface StripDropData {
  type: typeof STRIP_DROP_TYPE;
}

export interface BrowserTabDragData {
  type: "browser-tab";
  tabId: string;
}

export function isStripDropData(data: unknown): data is StripDropData {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === STRIP_DROP_TYPE
  );
}

export function isBrowserTabDragData(
  data: unknown,
): data is BrowserTabDragData {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === "browser-tab" &&
    typeof (data as { tabId?: unknown }).tabId === "string"
  );
}

export function stripTarget(target: unknown): { pillId: string | null } | null {
  if (isBrowserTabDragData(target)) return { pillId: target.tabId };
  if (isStripDropData(target)) return { pillId: null };
  return null;
}
