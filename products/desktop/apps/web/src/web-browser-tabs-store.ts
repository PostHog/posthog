import {
  type BrowserWindow,
  closeTab,
  closeTabs,
  newBlankTab,
  openOrFocusTab,
  setTabOrder,
  setTabTarget,
  setWindowActiveTab,
  type TabsSnapshot,
  type TabTarget,
  TypedEventEmitter,
  tabsSnapshotSchema,
} from "@posthog/shared";
import { readValidated, writeJson } from "./web-local-store";

// Per-device browser-tab strip for the web host, backed by localStorage.
//
// Desktop owns the tab strip in the Electron main process: a single SQLite-backed
// BrowserTabsService instance shared across every window, fanning changes out via
// a snapshotChange event. The browser has one window and no such backend, so this
// is the scaled-down equivalent — it applies the EXACT same shared pure transforms
// the desktop service does (no logic duplication), persists the snapshot to
// localStorage, and emits the same snapshotChange event the renderer mirror and
// the host-router `browserTabs` slice both consume. Scope matches the other web
// stores (workspaces, archive, task metadata): state is per-browser and survives
// reloads.

const STORAGE_KEY = "posthog-code:web-browser-tabs";
const makeId = () => crypto.randomUUID();
const now = () => Date.now();

const EMPTY_SNAPSHOT: TabsSnapshot = { windows: [], tabs: [] };

type SnapshotChangeEvents = { snapshotChange: TabsSnapshot };

function load(): TabsSnapshot {
  return readValidated(STORAGE_KEY, tabsSnapshotSchema, () => EMPTY_SNAPSHOT);
}

class WebBrowserTabsStore extends TypedEventEmitter<SnapshotChangeEvents> {
  private snapshot: TabsSnapshot;

  constructor() {
    super();
    this.setMaxListeners(0);
    const loaded = load();
    const seeded = this.ensurePrimaryWindow(loaded);
    this.snapshot = seeded;
    if (seeded !== loaded) this.persist();
  }

  /** Guarantee a primary window exists so the first open has somewhere to land. */
  private ensurePrimaryWindow(snapshot: TabsSnapshot): TabsSnapshot {
    if (snapshot.windows.some((w) => w.isPrimary)) return snapshot;
    const primary: BrowserWindow = {
      id: makeId(),
      isPrimary: true,
      bounds: null,
      activeTabId: null,
    };
    return { ...snapshot, windows: [primary, ...snapshot.windows] };
  }

  getSnapshot(): TabsSnapshot {
    return this.snapshot;
  }

  getPrimaryWindowId(): string {
    const primary = this.snapshot.windows.find((w) => w.isPrimary);
    if (!primary) throw new Error("browser-tabs: no primary window");
    return primary.id;
  }

  openOrFocus(
    input: TabTarget & {
      windowId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
      tabId?: string;
    },
  ): TabsSnapshot {
    // Honor a renderer-minted id so the caller's optimistic apply and this
    // persisted state agree on the id.
    const providedId = input.tabId;
    const { snapshot } = openOrFocusTab(this.snapshot, {
      ...input,
      makeId: providedId ? () => providedId : makeId,
      now,
    });
    return this.commit(snapshot);
  }

  newBlankTab(input: { windowId: string; tabId?: string }): TabsSnapshot {
    const providedId = input.tabId;
    // Idempotent on the renderer-minted id: a replay must not append a second tab.
    if (providedId && this.snapshot.tabs.some((t) => t.id === providedId)) {
      return this.snapshot;
    }
    const { snapshot } = newBlankTab(this.snapshot, {
      windowId: input.windowId,
      makeId: providedId ? () => providedId : makeId,
      now,
    });
    return this.commit(snapshot);
  }

  setTabTarget(
    input: TabTarget & {
      tabId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
    },
  ): TabsSnapshot {
    return this.commit(setTabTarget(this.snapshot, { ...input, now }));
  }

  close(tabId: string): TabsSnapshot {
    const { snapshot } = closeTab(this.snapshot, tabId);
    return this.commit(snapshot);
  }

  closeMany(tabIds: string[], focusTabId?: string | null): TabsSnapshot {
    return this.commit(closeTabs(this.snapshot, tabIds, focusTabId));
  }

  setOrder(input: { windowId: string; tabIds: string[] }): TabsSnapshot {
    return this.commit(
      setTabOrder(this.snapshot, input.windowId, input.tabIds),
    );
  }

  setActiveTab(input: {
    windowId: string;
    tabId: string | null;
  }): TabsSnapshot {
    const next = setWindowActiveTab(this.snapshot, input.windowId, input.tabId);
    if (next === this.snapshot) return this.snapshot;
    return this.commit(next);
  }

  snapshotChangeEvents(
    signal: AbortSignal | undefined,
  ): AsyncIterable<TabsSnapshot> {
    return this.toIterable("snapshotChange", { signal });
  }

  private commit(next: TabsSnapshot): TabsSnapshot {
    this.snapshot = next;
    this.persist();
    this.emit("snapshotChange", next);
    return next;
  }

  private persist(): void {
    writeJson(STORAGE_KEY, this.snapshot);
  }
}

export const webBrowserTabsStore = new WebBrowserTabsStore();
