import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PresenceIntent } from "./schemas";

// Mock the scoped logger (the real one pulls in electron-log).
vi.mock("../../utils/logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

// Controllable settings instead of the electron-store singleton.
const settings = vi.hoisted(() => ({
  values: {} as Record<string, boolean>,
}));
vi.mock("../settingsStore", () => ({
  settingsStore: {
    get: (key: string, def: boolean) => settings.values[key] ?? def,
    set: (key: string, value: boolean) => {
      settings.values[key] = value;
    },
  },
}));

// Stub the IPC client so we can assert whether a connection was ever opened —
// and so node:net never runs in the test environment. A regular function (not
// an arrow) is used so the mock is constructable via `new`.
vi.mock("./discord-ipc", () => ({
  DiscordIpcClient: vi.fn(function (this: Record<string, unknown>) {
    this.on = vi.fn();
    this.connect = vi.fn();
    this.destroy = vi.fn();
    this.setActivity = vi.fn();
  }),
}));

// A real client id so the "not configured" guard is never the reason a
// connection is skipped — we want to prove the *enabled* gate does the work.
vi.mock("./constants", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./constants")>();
  return { ...actual, getDiscordClientId: () => "test-client-id" };
});

import { DiscordIpcClient } from "./discord-ipc";
import { DiscordPresenceService } from "./service";

const SAMPLE_INTENT: PresenceIntent = {
  hasActiveTask: true,
  taskTitle: "Repository overview",
  repoName: "posthog/posthog",
  agentRunning: true,
};

// The `this` captured for each `new DiscordIpcClient()` call.
const clientInstance = (index: number) =>
  vi.mocked(DiscordIpcClient).mock.instances[index] as unknown as {
    connect: ReturnType<typeof vi.fn>;
    destroy: ReturnType<typeof vi.fn>;
  };

describe("DiscordPresenceService connection gating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings.values = {
      discordPresenceEnabled: false,
      discordPresenceShowTaskTitle: false,
      discordPresenceShowRepoName: false,
    };
  });

  it("does not connect to Discord on construction when disabled", () => {
    const service = new DiscordPresenceService();
    expect(DiscordIpcClient).not.toHaveBeenCalled();
    expect(service.getState().connected).toBe(false);
  });

  it("does not connect when activity or privacy updates arrive while disabled", () => {
    const service = new DiscordPresenceService();
    service.setActivity(SAMPLE_INTENT);
    service.setShowTaskTitle(true);
    service.setShowRepoName(true);
    expect(DiscordIpcClient).not.toHaveBeenCalled();
  });

  it("connects only once enabled, and tears down when turned back off", () => {
    const service = new DiscordPresenceService();
    expect(DiscordIpcClient).not.toHaveBeenCalled();

    service.setEnabled(true);
    expect(DiscordIpcClient).toHaveBeenCalledTimes(1);
    expect(clientInstance(0).connect).toHaveBeenCalledTimes(1);

    service.setEnabled(false);
    expect(clientInstance(0).destroy).toHaveBeenCalledTimes(1);

    // Activity pushed after disabling must not spin up a new connection.
    service.setActivity(SAMPLE_INTENT);
    expect(DiscordIpcClient).toHaveBeenCalledTimes(1);
  });

  it("connects on construction when already enabled (guard sanity check)", () => {
    settings.values.discordPresenceEnabled = true;
    new DiscordPresenceService();
    expect(DiscordIpcClient).toHaveBeenCalledTimes(1);
    expect(clientInstance(0).connect).toHaveBeenCalledTimes(1);
  });
});
