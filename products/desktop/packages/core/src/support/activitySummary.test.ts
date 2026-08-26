import type { SupportActivityEntry } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { activityActorLabel, summarizeActivity } from "./activitySummary";

function entry(overrides: Partial<SupportActivityEntry>): SupportActivityEntry {
  return {
    id: "00000000-0000-0000-0000-000000000000",
    activity: "updated",
    created_at: "2026-08-12T12:00:00Z",
    ...overrides,
  };
}

describe("activity summaries", () => {
  it.each<[string, Partial<SupportActivityEntry>, string]>([
    [
      "a person with a name",
      { user: { first_name: "Kim", last_name: "Turner" } },
      "Kim Turner",
    ],
    [
      "a person with only an email",
      { user: { email: "kim@example.com" } },
      "kim@example.com",
    ],
    ["an automated change", { user: null, is_system: true }, "PostHog"],
    ["an unattributed change", { user: null }, "Unknown"],
  ])("names the actor for %s", (_case, overrides, expected) => {
    expect(activityActorLabel(entry(overrides))).toBe(expected);
  });

  it.each<[string, Partial<SupportActivityEntry>, string]>([
    ["creation", { activity: "created" }, "created the ticket"],
    [
      "a status change",
      { detail: { changes: [{ field: "status", after: "resolved" }] } },
      "set status to resolved",
    ],
    [
      "a cleared field",
      {
        detail: {
          changes: [{ field: "priority", before: "high", after: null }],
        },
      },
      "cleared priority",
    ],
    [
      "an assignment",
      {
        detail: {
          changes: [
            {
              field: "assignee",
              after: { user: { email: "kim@example.com" } },
            },
          ],
        },
      },
      "set assignee to kim@example.com",
    ],
    [
      "an added tag",
      {
        detail: {
          changes: [
            {
              field: "tags",
              before: ["billing"],
              after: ["billing", "urgent"],
            },
          ],
        },
      },
      "added urgent",
    ],
    [
      "a removed tag",
      {
        detail: {
          changes: [
            {
              field: "tags",
              before: ["billing", "urgent"],
              after: ["billing"],
            },
          ],
        },
      },
      "removed urgent",
    ],
    [
      "a tag the backend reports on its own",
      {
        detail: {
          changes: [{ field: "tag", before: null, after: "exports" }],
        },
      },
      "added exports",
    ],
    [
      "a single tag being removed",
      {
        detail: {
          changes: [{ field: "tag", before: "exports", after: null }],
        },
      },
      "removed exports",
    ],
    [
      "several changes at once",
      {
        detail: {
          changes: [
            { field: "status", after: "open" },
            { field: "priority", after: "high" },
          ],
        },
      },
      "set status to open, set priority to high",
    ],
    [
      "a change with no detail",
      { detail: { changes: [] } },
      "updated the ticket",
    ],
  ])("summarizes %s", (_case, overrides, expected) => {
    expect(summarizeActivity(entry(overrides))).toBe(expected);
  });
});
