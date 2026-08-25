/**
 * Route prefixes that moved when the app's routes were flattened. Saved
 * locations are raw hrefs (the startup location, and every persisted browser
 * tab), so an install that last quit on an old path would otherwise reopen on
 * a route that no longer exists.
 *
 * Lives in shared because both the renderer (startup location) and the main
 * process (the tab repository) have to apply it.
 */
const MOVED_PREFIXES: readonly (readonly [string, string])[] = [
  ["/website/command-center", "/command-center"],
  ["/website/mcp-servers", "/mcp-servers"],
  ["/website/activity", "/activity"],
  ["/website/skills", "/skills"],
  ["/website/feeds", "/feeds"],
  ["/website/home", "/"],
  ["/website/new", "/new"],
  ["/website", "/spaces"],
  ["/code/inbox", "/inbox"],
  ["/code/agents", "/agents"],
  ["/code/archived", "/archived"],
  ["/code/loops", "/loops"],
  ["/code/tasks", "/tasks"],
  ["/code/pr", "/pr"],
  ["/code", "/new"],
];

// Longest first, so `/website/home` can never be eaten by `/website` however
// the list above is edited.
const MOVED_LONGEST_FIRST = [...MOVED_PREFIXES].sort(
  (a, b) => b[0].length - a[0].length,
);

/** A saved href on today's routes. Unrecognized hrefs are returned unchanged. */
export function rewriteSavedLocation(href: string): string {
  for (const [from, to] of MOVED_LONGEST_FIRST) {
    if (href === from) return to;
    const boundary = href[from.length];
    if (
      href.startsWith(from) &&
      (boundary === "/" || boundary === "?" || boundary === "#")
    ) {
      const rest = href.slice(from.length);
      if (to !== "/") return to + rest;
      return `/${rest.replace(/^\/+/, "")}`;
    }
  }
  return href;
}
