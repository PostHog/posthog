import type { DocSchemas } from "@posthog/api-client/docs";
import { describe, expect, it } from "vitest";
import { watchTimeline } from "./watchTimeline";

const person: DocSchemas.DocPerson = {
  id: 1,
  uuid: "u1",
  first_name: "Shy",
  last_name: "",
  email: "shy@example.com",
};

function post(
  overrides: Partial<DocSchemas.DiscussionPost>,
): DocSchemas.DiscussionPost {
  return {
    id: overrides.id ?? Math.random().toString(36),
    content: "",
    created_by: null,
    created_at: "2026-09-02T09:00:00Z",
    author_kind: "system",
    sent_to_agent: false,
    ...overrides,
  };
}

describe("watchTimeline", () => {
  it("merges typed posts with the quiet checks the evidence remembers, oldest first", () => {
    const thread: DocSchemas.DiscussionThread = {
      ...post({
        id: "t",
        created_at: "2026-09-01T09:00:00Z",
        author_kind: "human",
        created_by: person,
      }),
      anchor_key: "w1",
      anchor_text: "signups grow",
      resolved: false,
      kind: "watch",
      task_id: null,
      answer: null,
      replies: [
        post({
          id: "b",
          created_at: "2026-09-01T09:05:00Z",
          content: "Watching. 1 check runs daily.",
          event: "brief",
        }),
        post({
          id: "m",
          created_at: "2026-09-03T09:00:00Z",
          content: "“signups” moved from 5 to 2.",
          event: "moved",
        }),
        post({
          id: "r",
          created_at: "2026-09-03T10:00:00Z",
          author_kind: "agent",
          content: "**Signups fell in the EU**\n\nThe drop is all in the EU.",
          event: "report",
        }),
        post({
          id: "n",
          created_at: "2026-09-03T11:00:00Z",
          author_kind: "human",
          created_by: person,
          content: "Looking.",
        }),
      ],
      watch: {
        status: "active",
        stopped_reason: null,
        verdict: { verdict: "moved", reason: "", by: "page", at: null },
        brief: {
          claim: "signups grow",
          confirms: "",
          refutes: "",
          signals: [],
          submitted_at: null,
          evidence: [
            {
              label: "signups",
              query: "SELECT 1",
              shape: "number",
              baseline: 5,
              value: 2,
              checked_at: "2026-09-03T09:00:00Z",
              error: null,
              moved: true,
              history: [
                ["2026-09-01T09:05:00Z", 5],
                ["2026-09-02T09:00:00Z", 5],
                ["2026-09-03T09:00:00Z", 2],
              ],
            },
          ],
        },
        scout: null,
        scout_error: null,
        next_check_at: null,
        checked_at: null,
        evidence_only: false,
      },
    };

    const entries = watchTimeline(
      thread,
      (who) => who?.first_name ?? "Someone",
    );

    expect(entries.map((entry) => [entry.kind, entry.title])).toEqual([
      ["started", "Watch started"],
      ["brief", "Watching. 1 check runs daily."],
      ["check", "5 signups"],
      ["check", "5 signups"],
      ["moved", "“signups” moved from 5 to 2."],
      ["report", "Signups fell in the EU"],
      ["comment", "Looking."],
    ]);
    expect(entries[0].who).toBe("Shy");
    expect(entries[5].body).toContain("The drop is all in the EU.");
  });
});
