import { describe, expect, it } from "vitest";
import {
  isMethod,
  isNotification,
  POSTHOG_METHODS,
  POSTHOG_NOTIFICATIONS,
} from "./acp-extensions";

describe("isNotification", () => {
  it("matches the exact notification name", () => {
    expect(
      isNotification(
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      ),
    ).toBe(true);
  });

  it("matches the double-underscore prefix variant", () => {
    expect(
      isNotification(
        `_${POSTHOG_NOTIFICATIONS.TURN_COMPLETE}`,
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      ),
    ).toBe(true);
  });

  it("returns false for a different notification", () => {
    expect(
      isNotification(
        POSTHOG_NOTIFICATIONS.USAGE_UPDATE,
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      ),
    ).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isNotification(undefined, POSTHOG_NOTIFICATIONS.TURN_COMPLETE)).toBe(
      false,
    );
  });
});

describe("isMethod", () => {
  it("matches the exact method name", () => {
    expect(
      isMethod(
        POSTHOG_METHODS.REFRESH_SESSION,
        POSTHOG_METHODS.REFRESH_SESSION,
      ),
    ).toBe(true);
  });

  it("matches the double-underscore prefix variant", () => {
    expect(
      isMethod(
        `_${POSTHOG_METHODS.REFRESH_SESSION}`,
        POSTHOG_METHODS.REFRESH_SESSION,
      ),
    ).toBe(true);
  });

  it("returns false for unrelated method strings", () => {
    expect(isMethod("session/prompt", POSTHOG_METHODS.REFRESH_SESSION)).toBe(
      false,
    );
  });

  it("returns false for undefined", () => {
    expect(isMethod(undefined, POSTHOG_METHODS.REFRESH_SESSION)).toBe(false);
  });
});
