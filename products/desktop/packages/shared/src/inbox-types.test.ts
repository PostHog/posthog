import { describe, expect, it } from "vitest";
import type { SourceProduct } from "./inbox-types";
import { filterInboxSourceOptions } from "./inbox-types";

// A minimal mix of native products (session_replay, signals_scout) and
// warehouse-backed products (github, sentry) from the shared registry.
const OPTIONS: { value: SourceProduct }[] = [
  { value: "session_replay" },
  { value: "signals_scout" },
  { value: "github" },
  { value: "sentry" },
];

const values = (
  enabled: ReadonlySet<string> | undefined,
  selected: SourceProduct[] = [],
): SourceProduct[] =>
  filterInboxSourceOptions(OPTIONS, enabled, selected).map((o) => o.value);

describe("filterInboxSourceOptions", () => {
  it.each([
    {
      name: "shows an enabled warehouse source and hides a disabled one",
      enabled: new Set(["github"]),
      selected: [] as SourceProduct[],
      expected: ["session_replay", "signals_scout", "github"],
    },
    {
      name: "keeps PostHog's own products when nothing is enabled",
      enabled: new Set<string>(),
      selected: [] as SourceProduct[],
      expected: ["session_replay", "signals_scout"],
    },
    {
      name: "keeps a disabled source while it is selected",
      enabled: new Set<string>(),
      selected: ["sentry"] as SourceProduct[],
      expected: ["session_replay", "signals_scout", "sentry"],
    },
    {
      name: "hides nothing while the enabled set is unknown",
      enabled: undefined,
      selected: [] as SourceProduct[],
      expected: ["session_replay", "signals_scout", "github", "sentry"],
    },
  ])("$name", ({ enabled, selected, expected }) => {
    expect(values(enabled, selected)).toEqual(expected);
  });
});
