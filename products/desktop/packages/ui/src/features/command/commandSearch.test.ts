import {
  addRecentCommand,
  matchesCommandSearch,
  prioritizeExactCommandMatches,
} from "@posthog/ui/features/command/commandSearch";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/useSearchSections";
import { describe, expect, it } from "vitest";

const command = (id: string, label: string): Command => ({
  id,
  label,
  icon: null,
  action: "open-task",
  onRun: () => {},
});

describe("prioritizeExactCommandMatches", () => {
  it("places an exact label match before partial matches from earlier sections", () => {
    const sections: CommandSection[] = [
      { label: "Actions", items: [command("new", "New release task")] },
      { label: "Tasks", items: [command("release", "Release")] },
    ];

    const prioritized = prioritizeExactCommandMatches(sections, " release ");

    expect(prioritized.map((section) => section.label)).toEqual([
      "Exact matches",
      "Actions",
    ]);
    expect(
      prioritized.map((section) => section.items.map((item) => item.id)),
    ).toEqual([["release"], ["new"]]);
  });

  it("matches a query with surrounding whitespace", () => {
    expect(
      matchesCommandSearch(command("release", "Release"), " release "),
    ).toBe(true);
  });

  it("keeps the five most recently selected commands without duplicates", () => {
    const selected = ["one", "two", "three", "four", "five", "six"].reduce(
      (recent, id) => addRecentCommand(recent, command(id, id)),
      [] as Command[],
    );

    expect(
      addRecentCommand(selected, command("four", "four")).map(
        (item) => item.id,
      ),
    ).toEqual(["four", "six", "five", "three", "two"]);
  });
});
