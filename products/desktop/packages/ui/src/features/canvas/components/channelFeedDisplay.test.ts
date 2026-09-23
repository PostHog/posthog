import { describe, expect, it } from "vitest";
import { buildFeedSections, type FeedEntry } from "./channelFeedDisplay";

function task(id: string, repository: string | null): FeedEntry {
  return {
    kind: "task",
    id,
    createdAt: "2026-09-18T10:00:00Z",
    task: { id, repository } as FeedEntry extends { task: infer T } ? T : never,
  } as FeedEntry;
}

describe("buildFeedSections", () => {
  it("gives a group one section however often the list returns to it", () => {
    const sections = buildFeedSections(
      [
        task("a", "posthog/posthog"),
        task("b", null),
        task("c", "posthog/posthog"),
        task("d", "posthog/charts"),
        task("e", null),
      ],
      {
        labelOf: (entry) =>
          entry.kind === "task"
            ? (entry.task.repository ?? "No repository")
            : "No repository",
      },
    );

    expect(sections.map((s) => s.label)).toEqual([
      "posthog/posthog",
      "No repository",
      "posthog/charts",
    ]);
    expect(sections[0].entries.map((e) => e.id)).toEqual(["a", "c"]);
    expect(sections[1].entries.map((e) => e.id)).toEqual(["b", "e"]);
  });

  it("keeps sections apart when a key separates two equal labels", () => {
    const sections = buildFeedSections(
      [task("a", null), task("b", null), task("c", null)],
      {
        labelOf: () => "SEP 18",
        keyOf: (entry) => (entry.id === "b" ? "y" : "x"),
      },
    );

    expect(sections.map((s) => s.key)).toEqual(["x", "y"]);
    expect(sections[0].entries.map((e) => e.id)).toEqual(["a", "c"]);
  });

  it("runs an unlabelled list together as one section", () => {
    const sections = buildFeedSections([task("a", null), task("b", null)], {
      labelOf: () => null,
    });

    expect(sections).toHaveLength(1);
    expect(sections[0].label).toBeNull();
    expect(sections[0].entries).toHaveLength(2);
  });
});
