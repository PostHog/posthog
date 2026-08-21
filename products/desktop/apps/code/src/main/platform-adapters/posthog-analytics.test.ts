import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockCapture = vi.hoisted(() => vi.fn());
const mockCaptureException = vi.hoisted(() => vi.fn());
const mockIdentify = vi.hoisted(() => vi.fn());
const mockShutdown = vi.hoisted(() => vi.fn());
const MockPostHog = vi.hoisted(() => vi.fn());

vi.mock("posthog-node", () => ({ PostHog: MockPostHog }));

import { posthogNodeAnalytics } from "./posthog-analytics";

describe("posthog-analytics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockPostHog.mockImplementation(function (this: Record<string, unknown>) {
      this.capture = mockCapture;
      this.captureException = mockCaptureException;
      this.identify = mockIdentify;
      this.shutdown = mockShutdown;
    });
    process.env.VITE_POSTHOG_API_KEY = "test-key";
    posthogNodeAnalytics.resetUser();
    posthogNodeAnalytics.initialize();
  });

  afterEach(async () => {
    await posthogNodeAnalytics.shutdown();
  });

  it("includes the app version on every tracked event", () => {
    posthogNodeAnalytics.track("app_started");

    expect(mockCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        event: "app_started",
        properties: expect.objectContaining({
          team: "posthog-code",
          app_version: "0.0.0-test",
        }),
      }),
    );
  });

  it("lets caller-supplied properties coexist with the app version", () => {
    posthogNodeAnalytics.track("app_quit", { reason: "user-initiated" });

    expect(mockCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        properties: expect.objectContaining({
          reason: "user-initiated",
          app_version: "0.0.0-test",
        }),
      }),
    );
  });

  it("does not let caller-supplied app_version override the system value", () => {
    posthogNodeAnalytics.track("app_quit", { app_version: "spoofed" });

    expect(mockCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        properties: expect.objectContaining({
          app_version: "0.0.0-test",
        }),
      }),
    );
  });

  it("includes the app version on captured exceptions", () => {
    posthogNodeAnalytics.captureException(new Error("boom"));

    expect(mockCaptureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.any(String),
      expect.objectContaining({
        team: "posthog-code",
        app_version: "0.0.0-test",
      }),
    );
  });

  it("does not let additionalProperties override app_version on exceptions", () => {
    posthogNodeAnalytics.captureException(new Error("boom"), {
      app_version: "spoofed",
    });

    expect(mockCaptureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.any(String),
      expect.objectContaining({
        app_version: "0.0.0-test",
      }),
    );
  });

  it("stamps the main-owned session id and ignores a caller override", () => {
    posthogNodeAnalytics.captureException(new Error("boom"), {
      $session_id: "spoofed",
    });

    const [, , props] = mockCaptureException.mock.calls.at(-1) ?? [];
    expect(props.$session_id).toBe(posthogNodeAnalytics.getOrCreateSessionId());
  });

  it("mints a stable valid uuidv7 session id", () => {
    const first = posthogNodeAnalytics.getOrCreateSessionId();

    expect(posthogNodeAnalytics.getOrCreateSessionId()).toBe(first);
    expect(first).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
