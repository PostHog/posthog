import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type AnalyticsClient,
  captureException,
  identify,
  startAnalytics,
  stopAnalytics,
  track,
} from "./analytics";

const fakeClient = (): AnalyticsClient => ({
  capture: vi.fn(),
  identify: vi.fn(),
  captureException: vi.fn(),
  shutdown: vi.fn(async () => {}),
});

describe("analytics", () => {
  afterEach(() => stopAnalytics());

  it("tags every event and exception as the tui, in one session, for the signed-in user", () => {
    const client = fakeClient();
    startAnalytics(client);
    track("pane split", { direction: "row" });
    identify("user-1");
    captureException(new Error("boom"), { scope: "render" });

    const [event] = vi.mocked(client.capture).mock.calls[0];
    expect(event).toMatchObject({
      distinctId: "anonymous-tui",
      event: "tui pane split",
      properties: {
        app: "tui",
        direction: "row",
        $process_person_profile: false,
      },
    });
    const [, distinctId, properties] = vi.mocked(client.captureException).mock
      .calls[0];
    expect(distinctId).toBe("user-1");
    expect(properties).toMatchObject({
      app: "tui",
      scope: "render",
      $session_id: event.properties?.$session_id,
      $process_person_profile: true,
    });
  });

  it("sends nothing without a client", () => {
    expect(() => track("tui opened")).not.toThrow();
  });
});
