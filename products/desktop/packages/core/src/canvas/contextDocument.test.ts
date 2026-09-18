import { describe, expect, it } from "vitest";
import {
  parseContextDocument,
  serializeContextDocument,
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
  - name: Weekly paid bills
    why: Paid bills are the one number that says growth works.
    primary: true
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
        name: "Weekly paid bills",
        why: "Paid bills are the one number that says growth works.",
        primary: true,
        target: { direction: "at_least", value: 500, dueDate: "2026-10-31" },
        measure: {
          kind: "hogql",
          sql: "SELECT count()\nFROM events\nWHERE event = 'paid_bill'",
          trendSql: undefined,
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

  it("serializes prose alone without a frontmatter block", () => {
    const doc = parseContextDocument("# Just prose\n");

    expect(serializeContextDocument(doc)).toBe("# Just prose\n");
  });

  it.each([
    ["a goal without a name", "goals:\n  - why: no name here"],
    [
      "a target with an unknown direction",
      "goals:\n  - name: x\n    target:\n      direction: upwards\n      value: 1",
    ],
    [
      "a watched object with a non-http url",
      "watching:\n  - kind: flag\n    title: x\n    url: file:///etc/passwd",
    ],
  ])("refuses %s instead of dropping it on the next save", (_case, block) => {
    expect(() => parseContextDocument(`---\n${block}\n---\n`)).toThrow(
      /not in the expected shape/,
    );
  });
});
