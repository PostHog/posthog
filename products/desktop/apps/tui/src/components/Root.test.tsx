import { renderToString } from "ink";
import { describe, expect, it } from "vitest";
import type { TuiAuth } from "../auth";
import { Root } from "./Root";

describe("Root", () => {
  it.each([
    [
      "signed out",
      null,
      ["Sign in to PostHog", "US cloud", "EU cloud", "Local dev"],
    ],
    ["signed in", { apiHost: "https://us.posthog.com" } as TuiAuth, ["Work"]],
  ])("when %s shows the right screen", (_, auth, texts) => {
    const frame = renderToString(<Root initialAuth={auth} />);
    for (const text of texts) expect(frame).toContain(text);
  });
});
