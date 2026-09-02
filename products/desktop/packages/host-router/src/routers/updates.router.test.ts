import { describe, expect, it, vi } from "vitest";

const mockUpdatesService = {
  isEnabled: true,
  checkForUpdates: vi.fn(() => ({ success: true })),
  getStatus: vi.fn(() => ({
    checking: false,
    updateReady: true,
    version: "v2.0.0",
  })),
  installUpdate: vi.fn(() => Promise.resolve({ installed: true })),
  toIterable: vi.fn(),
};

import { updatesRouter } from "./updates.router";

const resolver = { get: <T>() => mockUpdatesService as T };

describe("updatesRouter", () => {
  it("returns the current update status snapshot", async () => {
    const caller = updatesRouter.createCaller({ container: resolver });

    await expect(caller.getStatus()).resolves.toEqual({
      checking: false,
      updateReady: true,
      version: "v2.0.0",
    });
    expect(mockUpdatesService.getStatus).toHaveBeenCalled();
  });

  it("delegates menu/user checks to the updates service", async () => {
    const caller = updatesRouter.createCaller({ container: resolver });

    await expect(caller.check()).resolves.toEqual({ success: true });
    expect(mockUpdatesService.checkForUpdates).toHaveBeenCalled();
  });

  it("reports whether updates are enabled", async () => {
    const caller = updatesRouter.createCaller({ container: resolver });

    await expect(caller.isEnabled()).resolves.toEqual({ enabled: true });
  });

  it("delegates install to the updates service", async () => {
    const caller = updatesRouter.createCaller({ container: resolver });

    await expect(caller.install()).resolves.toEqual({ installed: true });
    expect(mockUpdatesService.installUpdate).toHaveBeenCalled();
  });
});
