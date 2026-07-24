import { connectivityStore } from "@posthog/core/connectivity/connectivityStore";
import type { SessionService } from "@posthog/core/sessions/sessionService";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NetworkReconnectContribution } from "./network-reconnect.contribution";

function makeSessionService() {
  return { recoverAfterReconnect: vi.fn() } as unknown as SessionService;
}

function setOnline(isOnline: boolean) {
  connectivityStore.getState().setOnline(isOnline);
}

describe("NetworkReconnectContribution", () => {
  beforeEach(() => {
    // Reset the process-wide singleton store between cases.
    setOnline(true);
  });

  it("recovers sessions on an offline -> online transition", () => {
    const sessionService = makeSessionService();
    new NetworkReconnectContribution(sessionService).start();

    setOnline(false);
    expect(sessionService.recoverAfterReconnect).not.toHaveBeenCalled();

    setOnline(true);
    expect(sessionService.recoverAfterReconnect).toHaveBeenCalledTimes(1);
  });

  it("does not recover when going online -> offline", () => {
    const sessionService = makeSessionService();
    new NetworkReconnectContribution(sessionService).start();

    setOnline(false);
    expect(sessionService.recoverAfterReconnect).not.toHaveBeenCalled();
  });

  it("does not recover on a redundant online update", () => {
    const sessionService = makeSessionService();
    new NetworkReconnectContribution(sessionService).start();

    setOnline(true);
    expect(sessionService.recoverAfterReconnect).not.toHaveBeenCalled();
  });

  it("recovers again on each offline -> online cycle", () => {
    const sessionService = makeSessionService();
    new NetworkReconnectContribution(sessionService).start();

    setOnline(false);
    setOnline(true);
    setOnline(false);
    setOnline(true);
    expect(sessionService.recoverAfterReconnect).toHaveBeenCalledTimes(2);
  });
});
