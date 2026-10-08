import { describe, expect, it } from "vitest";
import {
  parseContextDocument,
  parsePostHogObjectUrl,
  readAutonomy,
  serializeContextDocument,
  withAutonomy,
} from "./contextDocument";

const WIKI_LINES = [
  "team_id: 1",
  "channel_id: 2387a35c-a89f-4741-8300-4a6af42708dd",
  "summary: Growth context: paid plans, checkout and the numbers the team moves.",
  "status: active",
].join("\n");

const DOCUMENT = `---
${WIKI_LINES}
goals:
  - id: 7f1d4d1e-3b0f-4c7c-9a48-3a6c1a5f1e01
    name: Weekly paid bills
    primary: true
    period: week
    target:
      direction: at_least
      value: 500
      due_date: 2026-10-31
    measure:
      kind: hogql
      sql: |-
        SELECT count()
        FROM events
        WHERE event = 'paid_bill'
  - id: 0b2c9e4a-6d1f-4e3b-8a7c-5d9e1f2a3b4c
    name: "Share of paid bills: business plan"
    percent: true
    target:
      direction: at_most
      value: 0.3
    measure:
      kind: insight
      short_id: AbC123
      url: http://localhost:8010/project/1/insights/AbC123
      name: Bill's conversion
reading:
  - title: "#growth-team"
    target: https://slack.com/app_redirect?channel=growth-team
    note: Where the team talks.
  - title: plans-and-prices.md
    target: projects/1/spaces/hedgebox-growth/plans-and-prices.md
watching:
  - kind: flag
    title: retention-nudge-v1
    url: http://localhost:8010/project/1/feature_flags/8
---

# hedgebox-growth

Hedgebox is a file hosting product.

## Goals

This heading is prose now, not a section.
`;

describe("contextDocument", () => {
  it("round-trips the lists and keeps the wiki's own lines and the body as written", () => {
    const doc = parseContextDocument(DOCUMENT);

    expect(doc.frontmatter).toBe(WIKI_LINES);
    expect(doc.goals).toEqual([
      {
        id: "7f1d4d1e-3b0f-4c7c-9a48-3a6c1a5f1e01",
        name: "Weekly paid bills",
        primary: true,
        period: "week",
        percent: undefined,
        task: undefined,
        target: { direction: "at_least", value: 500, dueDate: "2026-10-31" },
        measure: {
          kind: "hogql",
          sql: "SELECT count()\nFROM events\nWHERE event = 'paid_bill'",
          trendSql: undefined,
        },
      },
      {
        id: "0b2c9e4a-6d1f-4e3b-8a7c-5d9e1f2a3b4c",
        name: "Share of paid bills: business plan",
        primary: false,
        period: undefined,
        percent: true,
        task: undefined,
        target: { direction: "at_most", value: 0.3, dueDate: null },
        measure: {
          kind: "insight",
          shortId: "AbC123",
          url: "http://localhost:8010/project/1/insights/AbC123",
          name: "Bill's conversion",
        },
      },
    ]);
    expect(doc.links.map((link) => link.note)).toEqual([
      "Where the team talks.",
      "",
    ]);
    expect(doc.objects).toEqual([
      {
        kind: "flag",
        title: "retention-nudge-v1",
        url: "http://localhost:8010/project/1/feature_flags/8",
      },
    ]);
    expect(doc.knowledge).toContain("## Goals\n\nThis heading is prose now");
    expect(serializeContextDocument(doc)).toBe(DOCUMENT);
  });

  it("gives a goal without an id one, and drops the task link once a measure exists", () => {
    const doc = parseContextDocument(
      "---\ngoals:\n  - name: Signups\n    task: 8f1c\n    measure:\n      kind: hogql\n      sql: SELECT count() FROM events\n---\n",
    );

    expect(doc.goals[0].id).toHaveLength(36);
    expect(doc.goals[0].task).toBe("8f1c");
    expect(serializeContextDocument(doc)).not.toContain("task:");
  });

  it("reads the autonomy level from the wiki's own lines and rewrites it in place", () => {
    const doc = parseContextDocument(
      "---\nsummary: Move activation\nautonomy: propose\nchannel_id: abc\n---\n\n# Body\n",
    );

    expect(readAutonomy(doc)).toBe("propose");
    const changed = withAutonomy(doc, "ship_drafts");
    expect(serializeContextDocument(changed)).toBe(
      "---\nsummary: Move activation\nautonomy: ship_drafts\nchannel_id: abc\n---\n\n# Body\n",
    );
    expect(
      readAutonomy(parseContextDocument("---\nsummary: x\n---\n")),
    ).toBeNull();
    expect(
      readAutonomy(parseContextDocument("---\nautonomy: whatever\n---\n")),
    ).toBeNull();
  });

  it("serializes prose alone without a frontmatter block", () => {
    const doc = parseContextDocument("# Just prose\n");

    expect(serializeContextDocument(doc)).toBe("# Just prose\n");
  });

  it.each([
    ["a goal without a name", "goals:\n  - primary: true"],
    [
      "a target with an unknown direction",
      "goals:\n  - name: x\n    target:\n      direction: upwards\n      value: 1",
    ],
    [
      "a watched object with a non-http url",
      "watching:\n  - kind: flag\n    title: x\n    url: file:///etc/passwd",
    ],
    ["a value YAML cannot read", "goals:\n  - name: x\n    unit: %"],
  ])(
    "keeps %s as a broken block and writes it back unchanged",
    (_case, block) => {
      const doc = parseContextDocument(
        `---\nsummary: s\n${block}\n---\n\nBody\n`,
      );

      expect(doc.broken).toHaveLength(1);
      expect(doc.broken[0].error).not.toBe("");
      expect(
        serializeContextDocument({ ...doc, goals: [], links: [], objects: [] }),
      ).toBe(`---\nsummary: s\n${block}\n---\n\nBody\n`);
    },
  );

  it.each([
    [
      "a flag on the signed-in host",
      "https://us.posthog.com/project/1/feature_flags/8",
      "flag",
    ],
    [
      "the same path on another host",
      "https://attacker.example/project/1/feature_flags/8",
      null,
    ],
    [
      "an event name with broken percent-encoding",
      "https://us.posthog.com/data-management/events/%E0%A4%A",
      "event",
    ],
  ])("reads %s", (_case, url, kind) => {
    expect(parsePostHogObjectUrl(url, "us.posthog.com")?.kind ?? null).toBe(
      kind,
    );
  });
});
