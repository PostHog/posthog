import type { HostTrpcClient } from "@posthog/host-router/client";
import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CustomInstructionsSyncContribution } from "./customInstructionsSync.contribution";
import { useSettingsStore } from "./settingsStore";

registerRendererStateStorage({
  getItem: vi.fn().mockResolvedValue(null),
  setItem: vi.fn().mockResolvedValue(undefined),
  removeItem: vi.fn().mockResolvedValue(undefined),
});

const query = vi.fn();
const client = {
  os: { getUserAgentInstructions: { query } },
} as unknown as HostTrpcClient;

const staleFile = {
  path: "/home/u/.claude/CLAUDE.md",
  displayPath: "~/.claude/CLAUDE.md",
  content: "stale",
  truncated: false,
};
const freshFile = { ...staleFile, content: "fresh" };

/**
 * Waits one macrotask turn so a resolved read's await continuation (and any
 * chained microtasks) lands before asserting.
 */
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

/** A promise plus its resolve handle, for settling a mocked read on cue. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const setSyncEnabled = (enabled: boolean) =>
  useSettingsStore.getState().setSyncCustomInstructionsFromFile(enabled);

describe("CustomInstructionsSyncContribution", () => {
  // The contribution subscribes to the module-level store and never
  // unsubscribes, so one shared instance serves every test.
  let started = false;

  beforeEach(() => {
    useSettingsStore.setState({
      _hasHydrated: true,
      syncCustomInstructionsFromFile: false,
      syncedCustomInstructions: null,
    });
    query.mockReset();
    if (!started) {
      new CustomInstructionsSyncContribution(client).start();
      started = true;
    }
  });

  it("reads the file when hydration completes with sync already on at boot", async () => {
    // The headline boot behaviour: the contribution starts before persist
    // rehydration flips _hasHydrated, and sync is persisted-on. The read must
    // fire on that false -> true transition, not only on a later toggle flip -
    // otherwise a user with sync persisted-on gets no file read at startup.
    useSettingsStore.setState({
      _hasHydrated: false,
      syncCustomInstructionsFromFile: true,
      syncedCustomInstructions: null,
    });
    query.mockResolvedValue(freshFile);

    // Rehydration flips this asynchronously, after start() has already run.
    useSettingsStore.setState({ _hasHydrated: true });
    await flush();

    expect(query).toHaveBeenCalled();
    expect(useSettingsStore.getState().syncedCustomInstructions).toEqual(
      freshFile,
    );
  });

  it("mirrors the file into the store when sync turns on", async () => {
    query.mockResolvedValueOnce(freshFile);

    setSyncEnabled(true);
    await flush();

    expect(useSettingsStore.getState().syncedCustomInstructions).toEqual(
      freshFile,
    );
  });

  it("clears the snapshot when sync turns off", async () => {
    query.mockResolvedValueOnce(freshFile);
    setSyncEnabled(true);
    await flush();

    setSyncEnabled(false);

    expect(useSettingsStore.getState().syncedCustomInstructions).toBeNull();
  });

  it("discards a read that resolves after sync was toggled off", async () => {
    const read = deferred<typeof staleFile>();
    query.mockReturnValueOnce(read.promise);

    setSyncEnabled(true);
    setSyncEnabled(false);
    read.resolve(staleFile);
    await flush();

    expect(useSettingsStore.getState().syncedCustomInstructions).toBeNull();
  });

  it("leaves personalization empty when the read fails, never a stale snapshot", async () => {
    // Seed a leftover snapshot directly: the failed-read semantics are
    // "clear first, so a rejected read leaves empty", and only a pre-seeded
    // snapshot can catch a refactor reverting that to keep-last-snapshot.
    useSettingsStore.setState({ syncedCustomInstructions: staleFile });
    query.mockRejectedValueOnce(new Error("read failed"));

    setSyncEnabled(true);
    await flush();

    expect(useSettingsStore.getState().syncedCustomInstructions).toBeNull();
  });

  it("keeps the newest read when re-enable reads resolve out of order", async () => {
    const firstRead = deferred<typeof staleFile>();
    const secondRead = deferred<typeof freshFile>();
    query
      .mockReturnValueOnce(firstRead.promise)
      .mockReturnValueOnce(secondRead.promise);

    setSyncEnabled(true);
    setSyncEnabled(false);
    setSyncEnabled(true);
    secondRead.resolve(freshFile);
    await flush();
    firstRead.resolve(staleFile);
    await flush();

    expect(useSettingsStore.getState().syncedCustomInstructions).toEqual(
      freshFile,
    );
  });
});
