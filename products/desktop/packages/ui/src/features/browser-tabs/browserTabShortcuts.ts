export function shouldHandleBrowserTabSwitch(
  event: Pick<KeyboardEvent, "ctrlKey" | "metaKey">,
  macPlatform: boolean,
): boolean {
  return !macPlatform || !event.ctrlKey || event.metaKey;
}

/**
 * The tab Ctrl+Tab (or Ctrl+Shift+Tab) moves to: one step through the
 * DISPLAYED order, wrapping at both ends the way a browser does. Reads display
 * order so the cycle follows the strip on screen, pinned tabs included.
 */
export function cycledTabId(
  displayedTabIds: string[],
  activeTabId: string | null,
  step: 1 | -1,
): string | null {
  if (displayedTabIds.length < 2) return null;
  const from = activeTabId ? displayedTabIds.indexOf(activeTabId) : -1;
  if (from === -1)
    return displayedTabIds[step === 1 ? 0 : displayedTabIds.length - 1];
  const to = (from + step + displayedTabIds.length) % displayedTabIds.length;
  return displayedTabIds[to];
}
