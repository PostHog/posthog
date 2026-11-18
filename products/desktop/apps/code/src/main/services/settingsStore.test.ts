import { beforeEach, describe, expect, it, vi } from "vitest";

const existingPaths = vi.hoisted(() => new Set<string>());
const storedSettings = vi.hoisted(() => new Map<string, unknown>());
const renameSync = vi.hoisted(() => vi.fn());

vi.mock("node:fs", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:fs")>();
  const existsSync = (filePath: string) => existingPaths.has(filePath);
  return {
    ...original,
    default: { ...original, existsSync, renameSync },
    existsSync,
    renameSync,
  };
});

vi.mock("node:os", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:os")>();
  return {
    ...original,
    default: { ...original, homedir: () => "/home/test" },
    homedir: () => "/home/test",
  };
});

vi.mock("../utils/env", () => ({
  getUserDataDir: () => "/tmp/posthog-code-test",
  isDevBuild: () => false,
}));

vi.mock("electron-store", () => ({
  default: class {
    private readonly defaults: Record<string, unknown>;

    constructor(options: { defaults: Record<string, unknown> }) {
      this.defaults = options.defaults;
    }

    get(key: string, fallback?: unknown): unknown {
      return storedSettings.has(key)
        ? storedSettings.get(key)
        : (this.defaults[key] ?? fallback);
    }

    set(key: string, value: unknown): void {
      storedSettings.set(key, value);
    }
  },
}));

async function loadSettingsStore() {
  return import("./settingsStore");
}

describe("workspace location compatibility", () => {
  beforeEach(() => {
    vi.resetModules();
    existingPaths.clear();
    storedSettings.clear();
    renameSync.mockClear();
  });

  it("uses the desktop directory for a new profile", async () => {
    const { getWorktreeLocation } = await loadSettingsStore();

    expect(getWorktreeLocation()).toBe("/home/test/.posthog-desktop/worktrees");
  });

  it("keeps the previous default when it is the only existing location", async () => {
    existingPaths.add("/home/test/.posthog-code/worktrees");

    const { getAllWorktreeLocations, getWorktreeLocation } =
      await loadSettingsStore();

    expect(getWorktreeLocation()).toBe("/home/test/.posthog-code/worktrees");
    expect(getAllWorktreeLocations()).toEqual([
      "/home/test/.posthog-code/worktrees",
    ]);
    expect(renameSync).not.toHaveBeenCalled();
  });

  it("discovers the previous default after the desktop directory exists", async () => {
    existingPaths.add("/home/test/.posthog-code/worktrees");
    existingPaths.add("/home/test/.posthog-desktop/worktrees");

    const { getAllWorktreeLocations, getWorktreeLocation } =
      await loadSettingsStore();

    expect(getWorktreeLocation()).toBe("/home/test/.posthog-desktop/worktrees");
    expect(getAllWorktreeLocations()).toEqual([
      "/home/test/.posthog-desktop/worktrees",
      "/home/test/.posthog-code/worktrees",
    ]);
  });
});
