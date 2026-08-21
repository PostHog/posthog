import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import type { TabsSnapshot } from "@posthog/shared";
import { beforeEach, describe, expect, it } from "vitest";
import {
  applyLocalTransform,
  applyRemoteSnapshot,
  persistWrite,
  registerSnapshotFetcher,
} from "./tabsSync";

function snap(tabIds: string[]): TabsSnapshot {
  return {
    windows: [
      {
        id: "w1",
        isPrimary: true,
        bounds: null,
        activeTabId: tabIds[0] ?? null,
      },
    ],
    tabs: tabIds.map((id, i) => ({
      id,
      windowId: "w1",
      dashboardId: null,
      taskId: null,
      channelId: `c-${id}`,
      channelSection: null,
      appView: null,
      position: (i + 1) * 1000,
      createdAt: i,
      lastActiveAt: i,
    })),
  };
}

const current = () => browserTabsStore.getState().snapshot;

// Resolvable promise helper so tests control settle order.
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("tabsSync", () => {
  beforeEach(() => {
    browserTabsStore.getState().setSnapshot(snap(["a"]));
    registerSnapshotFetcher(null);
  });

  it("applyLocalTransform writes the mirror synchronously", () => {
    applyLocalTransform(() => snap(["a", "b"]));
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);
  });

  it("drops remote snapshots while a write is in flight (stale echo)", async () => {
    const d = deferred<TabsSnapshot>();
    const settled = persistWrite(() => d.promise);
    registerSnapshotFetcher(async () => snap(["a", "b"]));

    applyLocalTransform(() => snap(["a", "b"]));
    // Echo of an older state arrives mid-flight — must not rewind the mirror.
    applyRemoteSnapshot(snap(["a"]));
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);

    d.resolve(snap(["a", "b"]));
    await settled;
    await Promise.resolve();
  });

  it("re-pulls changes from another window after a local write settles", async () => {
    const d = deferred<TabsSnapshot>();
    const fetched = deferred<TabsSnapshot>();
    registerSnapshotFetcher(() => fetched.promise);
    const settled = persistWrite(() => d.promise);

    applyLocalTransform(() => snap(["a", "b"]));
    applyRemoteSnapshot(snap(["a", "b", "remote"]));

    d.resolve(snap(["a", "b"]));
    await settled;
    fetched.resolve(snap(["a", "b", "remote"]));
    await fetched.promise;
    await Promise.resolve();

    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b", "remote"]);
  });

  it("does not overwrite a newer live push with a reconciliation fetch", async () => {
    const write = deferred<TabsSnapshot>();
    const fetched = deferred<TabsSnapshot>();
    registerSnapshotFetcher(() => fetched.promise);
    const settled = persistWrite(() => write.promise);

    applyRemoteSnapshot(snap(["a", "remote"]));
    write.resolve(snap(["a"]));
    await settled;

    applyRemoteSnapshot(snap(["a", "remote", "newer"]));
    fetched.resolve(snap(["a", "remote"]));
    await fetched.promise;
    await Promise.resolve();

    expect(current().tabs.map((t) => t.id)).toEqual(["a", "remote", "newer"]);
  });

  it("applies remote snapshots when idle", () => {
    applyRemoteSnapshot(snap(["a", "b", "c"]));
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b", "c"]);
  });

  it("only the LAST settling write applies its server snapshot", async () => {
    const d1 = deferred<TabsSnapshot>();
    const d2 = deferred<TabsSnapshot>();
    const p1 = persistWrite(() => d1.promise);
    const p2 = persistWrite(() => d2.promise);
    applyLocalTransform(() => snap(["a", "b"]));

    // First write settles while the second is still in flight: its (older)
    // snapshot must NOT be applied.
    d1.resolve(snap(["a"]));
    await p1;
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);

    // Last write settles: its snapshot is authoritative and applies.
    d2.resolve(snap(["a", "b"]));
    await p2;
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);
  });

  it("keeps the optimistic state when a write fails, and unblocks remote applies", async () => {
    const d = deferred<TabsSnapshot>();
    const settled = persistWrite(() => d.promise);
    applyLocalTransform(() => snap(["a", "b"]));

    d.reject(new Error("ipc down"));
    await settled; // must not throw

    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);
    // Gate reopened: the next remote snapshot reconciles.
    applyRemoteSnapshot(snap(["a", "b", "c"]));
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b", "c"]);
  });

  it("re-pulls the authoritative snapshot when the last in-flight write fails", async () => {
    // A failed mutation commits nothing server-side and emits no push, so the
    // failed-last-write path must reconcile via the registered fetcher.
    const fetched = deferred<TabsSnapshot>();
    registerSnapshotFetcher(() => fetched.promise);

    const d = deferred<TabsSnapshot>();
    const settled = persistWrite(() => d.promise);
    applyLocalTransform(() => snap(["a", "b"])); // optimistic, never committed

    d.reject(new Error("ipc down"));
    await settled;

    fetched.resolve(snap(["a"])); // server truth: the write never landed
    await fetched.promise;
    await Promise.resolve(); // let the .then apply
    expect(current().tabs.map((t) => t.id)).toEqual(["a"]);
  });

  it("skips the failure re-pull when a newer write is already in flight", async () => {
    const fetched = deferred<TabsSnapshot>();
    registerSnapshotFetcher(() => fetched.promise);

    const d1 = deferred<TabsSnapshot>();
    const d2 = deferred<TabsSnapshot>();
    const p1 = persistWrite(() => d1.promise);

    d1.reject(new Error("ipc down"));
    await p1; // failure re-pull kicked off (was last in flight)

    // A newer write starts before the re-pull resolves: its settle owns
    // reconciliation, so the stale re-pull must not apply.
    const p2 = persistWrite(() => d2.promise);
    applyLocalTransform(() => snap(["a", "b"]));
    fetched.resolve(snap(["a"]));
    await fetched.promise;
    await Promise.resolve();
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);

    d2.resolve(snap(["a", "b"]));
    await p2;
    expect(current().tabs.map((t) => t.id)).toEqual(["a", "b"]);
  });
});
