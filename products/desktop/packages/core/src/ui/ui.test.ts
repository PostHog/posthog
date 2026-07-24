import { describe, expect, it, vi } from "vitest";
import type { UiAuth } from "./ports";
import { UIServiceEvent } from "./schemas";
import { UIService } from "./ui";

function makeAuth(): UiAuth {
  return { invalidateAccessTokenForTest: vi.fn().mockResolvedValue(undefined) };
}

describe("UIService signal events", () => {
  it.each([
    ["openSettings", UIServiceEvent.OpenSettings],
    ["newTask", UIServiceEvent.NewTask],
    ["resetLayout", UIServiceEvent.ResetLayout],
    ["clearStorage", UIServiceEvent.ClearStorage],
  ] as const)("%s emits %s", (method, event) => {
    const service = new UIService(makeAuth());
    const listener = vi.fn();
    service.on(event, listener);

    (service[method] as () => void)();

    expect(listener).toHaveBeenCalledWith(true);
  });
});

describe("UIService.invalidateToken", () => {
  it("invalidates the access token before emitting the signal", async () => {
    const auth = makeAuth();
    const service = new UIService(auth);
    const listener = vi.fn();
    service.on(UIServiceEvent.InvalidateToken, listener);

    await service.invalidateToken();

    expect(auth.invalidateAccessTokenForTest).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(true);
  });
});
