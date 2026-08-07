import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import type { TabsSnapshot } from "@posthog/shared";

/**
 * Local-first sync policy for the browser-tabs mirror.
 *
 * Every tab operation applies its shared pure transform to the renderer mirror
 * synchronously (the UI renders from the mirror, so interactions are instant),
 * then persists to the main process in the background. Because the renderer
 * and the service run the SAME transforms in the SAME order, the mirror and
 * the durable snapshot converge.
 *
 * The hazard this module exists to prevent: the main process echoes every
 * commit back (the mutation's return value and the snapshotChange fan-out).
 * Under rapid input, the echo of write N arrives AFTER the local apply of
 * write N+1; applying it would rewind the mirror, and the navigation effect
 * would re-decide against stale state and misfire persistent writes (the
 * historical "tab targets swap / titles flicker" corruption). So while any
 * local write is in flight, remote snapshots are dropped. If a push arrives,
 * the renderer re-fetches the authoritative snapshot after the write batch
 * settles because it may contain another window's mutation. Otherwise the last
 * write response reconciles the mirror directly.
 */
let inFlight = 0;
let remoteSnapshotVersion = 0;
let needsAuthoritativeReconcile = false;

// Authoritative-snapshot fetcher, registered once at boot by the events
// contribution (tabsSync can't reach the injected BrowserTabsClient itself).
// Used to reconcile after a failed write or a dropped remote snapshot.
let fetchAuthoritative: (() => Promise<TabsSnapshot>) | null = null;

export function registerSnapshotFetcher(
  fetch: (() => Promise<TabsSnapshot>) | null,
): void {
  fetchAuthoritative = fetch;
}

function reconcileAuthoritative(): void {
  void reseedMirror().catch(() => undefined);
}

/**
 * Pull the authoritative snapshot and apply it to the mirror. Used to heal a
 * mirror that never seeded (the boot fetch raced or failed) — e.g. from the
 * new-tab handler when it finds no window to append into. Applies only if no
 * local write or newer remote push landed meanwhile, but always RETURNS the
 * fetched snapshot (null if no fetcher is registered) so a caller can act on
 * the server state even when the store apply was skipped. Rejects when the
 * fetch fails so callers can chain on success.
 */
export async function reseedMirror(): Promise<TabsSnapshot | null> {
  if (!fetchAuthoritative) return null;
  const versionAtRequest = remoteSnapshotVersion;
  const server = await fetchAuthoritative();
  if (inFlight === 0 && remoteSnapshotVersion === versionAtRequest) {
    browserTabsStore.getState().setSnapshot(server);
  }
  return server;
}

/** Read the mirror's current snapshot (non-reactive; for event handlers and
 * effects that must see the latest state without subscribing to it). */
export function readMirror(): TabsSnapshot {
  return browserTabsStore.getState().snapshot;
}

/** Synchronously apply a pure transform to the mirror (the optimistic write). */
export function applyLocalTransform(
  transform: (snapshot: TabsSnapshot) => TabsSnapshot,
): TabsSnapshot {
  const store = browserTabsStore.getState();
  const next = transform(store.snapshot);
  store.setSnapshot(next);
  return next;
}

/**
 * Persist a local write to the main process. Fire-and-forget from the caller's
 * perspective: the UI has already moved via applyLocalTransform. Only the last
 * settling write applies its server snapshot unless a remote push was dropped,
 * in which case an authoritative fetch reconciles cross-window state. Failed
 * writes are swallowed and reconciled through the same fetch path.
 */
export async function persistWrite(
  write: () => Promise<TabsSnapshot>,
): Promise<void> {
  inFlight++;
  let serverSnapshot: TabsSnapshot | null = null;
  try {
    serverSnapshot = await write();
  } catch {
    needsAuthoritativeReconcile = true;
  } finally {
    inFlight--;
    if (inFlight === 0) {
      if (needsAuthoritativeReconcile) {
        needsAuthoritativeReconcile = false;
        reconcileAuthoritative();
      } else if (serverSnapshot) {
        // Over Electron IPC the last-settling write is also the last-issued
        // write (single FIFO channel, synchronous service handlers). A transport
        // that can reorder responses will need a sequence guard here.
        browserTabsStore.getState().setSnapshot(serverSnapshot);
      }
    }
  }
}

/**
 * Apply a snapshot pushed from the main process (boot seed, or a mutation made
 * by another window). A push received during a local write is dropped and
 * replaced by an authoritative fetch when the write batch settles.
 */
export function applyRemoteSnapshot(snapshot: TabsSnapshot): void {
  remoteSnapshotVersion++;
  if (inFlight > 0) {
    // This may be an echo of our own write, or a real mutation from another
    // window. Re-pull once the local write batch settles so neither case can
    // rewind or strand the mirror.
    needsAuthoritativeReconcile = true;
    return;
  }
  browserTabsStore.getState().setSnapshot(snapshot);
}

// Dev-only inspection handle so the live mirror can be dumped from the console
// (and by agent-browser during dogfooding). No-op in production builds.
if (import.meta.env.DEV) {
  (globalThis as { __tabsMirror?: () => TabsSnapshot }).__tabsMirror = () =>
    browserTabsStore.getState().snapshot;
}
