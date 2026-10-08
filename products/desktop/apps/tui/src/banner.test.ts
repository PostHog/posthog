import { describe, expect, it } from "vitest";
import { bannerLines } from "./banner";

describe("bannerLines", () => {
  it("names the model, who pays and where a new chat runs", () => {
    expect(
      bannerLines({
        place: "local",
        cwd: "/Users/me/dev/posthog",
        home: "/Users/me",
        repositories: [],
        billing: "anthropic",
        model: "Fable 5.1 (high)",
      }),
    ).toEqual([
      "PostHog",
      "Fable 5.1 (high) • Anthropic subscription",
      "~/dev/posthog",
    ]);
    expect(
      bannerLines({
        place: "cloud",
        cwd: "/Users/me/dev/posthog",
        home: "/Users/me",
        repositories: ["PostHog/posthog"],
        billing: "posthog",
        model: "Opus 5.5",
      }),
    ).toEqual([
      "PostHog",
      "Opus 5.5 • PostHog billing",
      "Cloud run · PostHog/posthog",
    ]);
    expect(
      bannerLines({
        place: "cloud",
        cwd: "/x",
        home: "/x",
        repositories: [],
        billing: "chatgpt",
        model: undefined,
      }),
    ).toEqual(["PostHog", "ChatGPT subscription", "Cloud run"]);
  });
});
