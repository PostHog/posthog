/** How long two crashes must be apart before they stop counting as a loop. */
const ROUTE_CRASH_WINDOW_MS = 60_000;
/** Crashes on one route before the app stops loading that route. */
const ROUTE_CRASH_THRESHOLD = 2;

/**
 * The in-app route a renderer URL points at, in the form the app saves as its
 * startup location. The app uses hash routing, so the route is the fragment.
 */
export function appRouteFromUrl(url: string): string | null {
  const hashIndex = url.indexOf("#");
  if (hashIndex === -1) return null;
  const route = url.slice(hashIndex + 1);
  return route.startsWith("/") ? route : null;
}

export interface RouteCrashTracker {
  /** Records a crash and reports whether the route has now crashed too often. */
  record(route: string, now: number): boolean;
}

/**
 * A renderer crash is normally recoverable by a reload. A crash the route
 * itself causes is not: the reload keeps the fragment, so it lands on the same
 * route and crashes again. Count crashes per route so the caller can stop
 * loading a route that takes the window down every time.
 */
export function createRouteCrashTracker(): RouteCrashTracker {
  let current: { route: string; timestamps: number[] } | null = null;

  return {
    record(route, now) {
      if (current?.route !== route) {
        current = { route, timestamps: [] };
      }
      current.timestamps = current.timestamps.filter(
        (timestamp) => now - timestamp <= ROUTE_CRASH_WINDOW_MS,
      );
      current.timestamps.push(now);
      return current.timestamps.length >= ROUTE_CRASH_THRESHOLD;
    },
  };
}
