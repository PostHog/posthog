import { describe, expect, it } from "vitest";
import { selectAnnouncement } from "./selectAnnouncement";

const NOW = Date.parse("2026-08-05T12:00:00Z");
const APP_VERSION = "1.40.0";

function announcement(overrides: Record<string, unknown> = {}) {
  return {
    kind: "announcement",
    id: "a1",
    title: "Hello",
    body: "World",
    ...overrides,
  };
}

function requiredUpdate(overrides: Record<string, unknown> = {}) {
  return {
    kind: "required-update",
    id: "r1",
    title: "Update required",
    body: "Please update.",
    minVersion: "2.0.0",
    ...overrides,
  };
}

function select(
  payload: unknown,
  {
    now = NOW,
    appVersion = APP_VERSION as string | null,
    isDevBuild = false,
    dismissedIds = new Set<string>(),
    handledThisSession = false,
  } = {},
) {
  return selectAnnouncement({
    payload,
    now,
    appVersion,
    isDevBuild,
    dismissedIds,
    handledThisSession,
  });
}

describe("selectAnnouncement", () => {
  it("selects nothing when the app version is unknown", () => {
    const result = select(
      { announcements: [announcement(), requiredUpdate()] },
      { appVersion: null },
    );
    expect(result.active).toBeNull();
  });

  it("selects nothing in a development build", () => {
    const result = select(
      { announcements: [announcement(), requiredUpdate()] },
      { isDevBuild: true },
    );
    expect(result.active).toBeNull();
  });

  it.each([
    ["undefined payload", undefined],
    ["null payload", null],
    ["empty list", { announcements: [] }],
  ])("selects nothing for %s without a parse error", (_name, payload) => {
    const result = select(payload);
    expect(result.active).toBeNull();
    expect(result.parseError).toBe(false);
  });

  it.each([
    ["a string", "nope"],
    ["missing announcements key", { items: [] }],
    ["non-array announcements", { announcements: "all" }],
  ])("reports a parse error for %s", (_name, payload) => {
    const result = select(payload);
    expect(result.active).toBeNull();
    expect(result.parseError).toBe(true);
  });

  it("drops an invalid item but keeps its valid sibling", () => {
    const result = select({
      announcements: [{ garbage: true }, announcement()],
    });
    expect(result.invalidItems).toBe(1);
    expect(result.active?.announcement.id).toBe("a1");
  });

  it.each([
    ["before startsAt", { startsAt: "2026-08-06T00:00:00Z" }, false],
    ["after endsAt", { endsAt: "2026-08-04T00:00:00Z" }, false],
    [
      "inside window",
      { startsAt: "2026-08-01T00:00:00Z", endsAt: "2026-08-10T00:00:00Z" },
      true,
    ],
    ["no bounds", {}, true],
  ])("time window: %s", (_name, bounds, shown) => {
    const result = select({ announcements: [announcement(bounds)] });
    expect(result.active !== null).toBe(shown);
  });

  it("flags a schedule so callers re-evaluate on a timer", () => {
    expect(select({ announcements: [announcement()] }).hasSchedule).toBe(false);
    expect(
      select({
        announcements: [announcement({ startsAt: "2026-09-01T00:00:00Z" })],
      }).hasSchedule,
    ).toBe(true);
  });

  it.each([
    ["below minVersion", "2.0.0", true],
    ["at minVersion", APP_VERSION, false],
    ["above minVersion", "1.0.0", false],
  ])("required-update %s → shown %s", (_name, minVersion, shown) => {
    const result = select({ announcements: [requiredUpdate({ minVersion })] });
    expect(result.active !== null).toBe(shown);
    if (shown) expect(result.active?.needsUpdate).toBe(true);
  });

  it("required-update ignores dismissals", () => {
    const result = select(
      { announcements: [requiredUpdate()] },
      { dismissedIds: new Set(["r1"]) },
    );
    expect(result.active?.announcement.id).toBe("r1");
  });

  it.each([
    ["below minVersion", "2.0.0", true],
    ["at minVersion", APP_VERSION, false],
  ])("announcement %s → needsUpdate %s", (_name, minVersion, needsUpdate) => {
    const result = select({ announcements: [announcement({ minVersion })] });
    expect(result.active?.needsUpdate).toBe(needsUpdate);
  });

  it("retires an acknowledged requiresAck announcement", () => {
    const result = select(
      {
        announcements: [announcement({ style: "modal", requiresAck: true })],
      },
      { dismissedIds: new Set(["a1"]) },
    );
    expect(result.active).toBeNull();
  });

  it("skips dismissed announcements and falls through to the next on a fresh session", () => {
    const result = select(
      { announcements: [announcement(), announcement({ id: "a2" })] },
      { dismissedIds: new Set(["a1"]) },
    );
    expect(result.active?.announcement.id).toBe("a2");
  });

  it("shows no further announcement once one was handled this session", () => {
    const result = select(
      { announcements: [announcement(), announcement({ id: "a2" })] },
      { dismissedIds: new Set(["a1"]), handledThisSession: true },
    );
    expect(result.active).toBeNull();
  });

  it("still blocks on a required-update after an announcement was handled this session", () => {
    const result = select(
      { announcements: [announcement(), requiredUpdate()] },
      { dismissedIds: new Set(["a1"]), handledThisSession: true },
    );
    expect(result.active?.announcement.id).toBe("r1");
  });

  it("prefers an unmet required-update over an earlier announcement", () => {
    const result = select({
      announcements: [announcement(), requiredUpdate()],
    });
    expect(result.active?.announcement.id).toBe("r1");
  });

  it("uses payload order among equals", () => {
    const result = select({
      announcements: [announcement({ id: "first" }), announcement()],
    });
    expect(result.active?.announcement.id).toBe("first");
  });

  it("ignores a satisfied required-update and shows the announcement", () => {
    const result = select({
      announcements: [requiredUpdate({ minVersion: "1.0.0" }), announcement()],
    });
    expect(result.active?.announcement.id).toBe("a1");
  });
});
