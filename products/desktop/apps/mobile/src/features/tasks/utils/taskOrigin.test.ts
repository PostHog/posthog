import { Broadcast, Robot, SlackLogo } from "phosphor-react-native";
import { describe, expect, it } from "vitest";
import { getTaskOriginMeta } from "./taskOrigin";

describe("getTaskOriginMeta", () => {
  it.each<[string, string]>([
    ["slack", "From Slack"],
    ["signal_report", "From inbox"],
    ["signals_scout", "From Signals scout"],
    ["support_queue", "From support queue"],
    ["session_summaries", "From session summary"],
    ["error_tracking", "From error tracking"],
    ["eval_clusters", "From evals"],
    ["automation", "From automation"],
  ])("labels %s as %s", (origin, label) => {
    expect(getTaskOriginMeta(origin)?.label).toBe(label);
  });

  it.each<[string, unknown]>([
    ["slack", SlackLogo],
    ["signal_report", Broadcast],
    ["automation", Robot],
  ])("gives %s its own glyph", (origin, icon) => {
    expect(getTaskOriginMeta(origin)?.Icon).toBe(icon);
  });

  it("gives every known origin a distinct glyph", () => {
    const origins = [
      "slack",
      "signal_report",
      "signals_scout",
      "support_queue",
      "session_summaries",
      "error_tracking",
      "eval_clusters",
      "automation",
    ];
    const icons = origins.map((origin) => getTaskOriginMeta(origin)?.Icon);
    expect(new Set(icons).size).toBe(origins.length);
  });

  it.each<[string, string | null | undefined]>([
    ["a task the user typed", "user_created"],
    ["an origin this build has never heard of", "quantum_telepathy"],
    ["an empty string", ""],
    ["a null origin", null],
    ["a missing origin", undefined],
  ])("stays silent for %s", (_name, origin) => {
    expect(getTaskOriginMeta(origin)).toBeNull();
  });
});
