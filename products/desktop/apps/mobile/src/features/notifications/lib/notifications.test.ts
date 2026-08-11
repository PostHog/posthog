import { describe, expect, it, vi } from "vitest";

vi.mock("expo-constants", () => ({ default: { expoConfig: {} } }));
vi.mock("expo-device", () => ({ isDevice: true }));
vi.mock("expo-notifications", () => ({
  setNotificationHandler: vi.fn(),
  scheduleNotificationAsync: vi.fn(),
  getLastNotificationResponseAsync: vi.fn(),
  addNotificationResponseReceivedListener: vi.fn(),
}));
vi.mock("react-native", () => ({ Platform: { OS: "ios" } }));

import type * as Notifications from "expo-notifications";
import {
  extractTapPayload,
  resolveNotificationProjectSwitch,
} from "./notifications";

function responseWithData(
  data: Record<string, unknown> | undefined,
): Notifications.NotificationResponse {
  return {
    notification: { request: { content: { data } } },
  } as unknown as Notifications.NotificationResponse;
}

describe("extractTapPayload", () => {
  it("routes legacy taskId payloads without a team", () => {
    expect(responseTap({ taskId: "abc" })).toEqual({
      path: "/task/abc",
      teamId: undefined,
    });
  });

  it.each([
    { teamId: 42, expected: 42 },
    { teamId: "42", expected: 42 },
    { teamId: "not-a-number", expected: undefined },
    { teamId: -1, expected: undefined },
    { teamId: null, expected: undefined },
  ])("parses teamId $teamId as $expected", ({ teamId, expected }) => {
    expect(responseTap({ taskId: "abc", teamId })?.teamId).toBe(expected);
  });

  it("keeps the teamId on url-shaped payloads", () => {
    expect(responseTap({ url: "/task/abc", teamId: 7 })).toEqual({
      path: "/task/abc",
      teamId: 7,
    });
  });

  it("returns null without data", () => {
    expect(responseTap(undefined)).toBeNull();
  });
});

function responseTap(data: Record<string, unknown> | undefined) {
  return extractTapPayload(responseWithData(data));
}

describe("resolveNotificationProjectSwitch", () => {
  const base = {
    teamId: 7 as number | undefined,
    projectId: 2 as number | null,
    scopedTeams: [2, 7] as readonly number[],
    isLoading: false,
  };

  it.each([
    {
      name: "switches to a scoped foreign project",
      args: base,
      expected: { action: "switch", teamId: 7 },
    },
    {
      name: "navigates when already on the target project",
      args: { ...base, projectId: 7 },
      expected: { action: "navigate" },
    },
    {
      name: "blocks an out-of-scope project",
      args: { ...base, scopedTeams: [2] },
      expected: { action: "blocked" },
    },
    {
      name: "navigates for legacy payloads without a teamId",
      args: { ...base, teamId: undefined },
      expected: { action: "navigate" },
    },
    {
      name: "never blocks while auth is still loading",
      args: { ...base, isLoading: true, scopedTeams: [] },
      expected: { action: "navigate" },
    },
    {
      name: "never blocks before scoped teams hydrate",
      args: { ...base, scopedTeams: [] },
      expected: { action: "navigate" },
    },
  ])("$name", ({ args, expected }) => {
    expect(resolveNotificationProjectSwitch(args)).toEqual(expected);
  });
});
