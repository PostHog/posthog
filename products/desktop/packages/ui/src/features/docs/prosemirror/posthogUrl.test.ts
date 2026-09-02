import { describe, expect, it } from "vitest";
import { refFromUrl } from "./posthogUrl";

describe("refFromUrl", () => {
  it.each([
    [
      "http://localhost:8010/code/channel/11111111-2222-4333-8444-555555555555/tasks/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
      {
        type: "taskChip",
        attrs: { taskId: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", label: "" },
      },
    ],
    [
      "https://us.posthog.com/project/2/insights/abc123XY?dashboard=4#panel",
      {
        type: "objectChip",
        attrs: { kind: "insight", objectId: "abc123XY", label: "" },
      },
    ],
    [
      "https://eu.posthog.com/project/2/dashboard/42/",
      {
        type: "objectChip",
        attrs: { kind: "dashboard", objectId: "42", label: "" },
      },
    ],
    [
      "https://us.posthog.com/project/2/code/canvas/chan-1/91",
      {
        type: "objectChip",
        attrs: { kind: "dashboard", objectId: "91", label: "" },
      },
    ],
    [
      "https://us.posthog.com/project/2/replay/0198a-session",
      {
        type: "objectChip",
        attrs: { kind: "replay", objectId: "0198a-session", label: "" },
      },
    ],
    [
      "https://us.posthog.com/project/2/feature_flags/17",
      {
        type: "objectChip",
        attrs: { kind: "flag", objectId: "17", label: "" },
      },
    ],
    [
      "https://us.posthog.com/project/2/persons/019a-uuid",
      {
        type: "objectChip",
        attrs: { kind: "person", objectId: "019a-uuid", label: "" },
      },
    ],
  ])("reads %s", (url, expected) => {
    expect(refFromUrl(url)).toEqual(expected);
  });

  it.each([
    "https://us.posthog.com/project/2/insights/new",
    "https://us.posthog.com/project/2/feature_flags/my-flag-key",
    "https://us.posthog.com/project/2/insights",
    "see https://us.posthog.com/project/2/insights/abc123XY today",
    "not a url",
    "ftp://us.posthog.com/insights/abc",
  ])("leaves %s as text", (text) => {
    expect(refFromUrl(text)).toBeNull();
  });
});
