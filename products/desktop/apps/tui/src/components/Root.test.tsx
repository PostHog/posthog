import { renderToString } from "ink";
import { describe, expect, it } from "vitest";
import type { TuiAuth } from "../auth";
import { Root } from "./Root";

describe("Root", () => {
  it.each([
    ["signed out", null, "Sign in to PostHog"],
    ["signed in", {} as TuiAuth, "Work"],
  ])("when %s shows the right screen", (_, auth, text) => {
    expect(renderToString(<Root initialAuth={auth} />)).toContain(text);
  });
});
