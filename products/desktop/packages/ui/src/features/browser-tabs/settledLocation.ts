/**
 * The location the strip reconciles against, and the tab that entry belongs to,
 * **read from one snapshot**.
 *
 * During a pending navigation the router's `location` is already the
 * destination while `resolvedLocation` (and `matches`, and so `params`) still
 * describe the page being left. Taking the href from one and the tab tag from
 * the other pairs a tab with a location it was never on, and the strip's effect
 * then writes that location onto it — the "switching tabs rewrites another
 * tab's URL" corruption.
 *
 * Reading both off the settled snapshot keeps the pair coherent. `isCurrent`
 * additionally tells the effect not to act until that settled pair matches the
 * in-flight entry's href and tab owner. The in-flight `location` still drives
 * the strip's *highlight*, which wants to flip the instant you navigate; that
 * is a render, not a write.
 */
export interface RouterSnapshot {
  location: { href: string; state: { tabId?: string } };
  resolvedLocation?: { href: string; state: { tabId?: string } };
}

export interface SettledLocation {
  href: string;
  tabId: string | null;
  isCurrent: boolean;
}

export function settledLocation(state: RouterSnapshot): SettledLocation {
  const loc = state.resolvedLocation ?? state.location;
  const tabId = loc.state.tabId ?? null;
  const currentTabId = state.location.state.tabId ?? null;
  return {
    href: loc.href,
    tabId,
    isCurrent:
      !state.resolvedLocation ||
      (state.location.href === loc.href && currentTabId === tabId),
  };
}
