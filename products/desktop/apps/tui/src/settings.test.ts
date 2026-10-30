import { describe, expect, it } from "vitest";
import { settingsKey, settingsView, TOKEN_HINT } from "./settings";

const TOKEN = `sk-ant-oat01-${"x".repeat(40)}`;
const DOWN = "\u001b[B";
const ENTER = "\r";
const ESC = "\u001b";

describe("settingsKey", () => {
  it("toggles the Claude plan with Enter on the first row", () => {
    const { view, effect } = settingsKey(settingsView(false, false), ENTER);
    expect(view.planOn).toBe(true);
    expect(effect).toEqual({ kind: "setPlan", on: true });
  });

  it("saves a pasted token on Enter and rejects a bad one with a hint", () => {
    const typing = settingsKey(settingsView(false, false), "sk-ant-api03-x");
    expect(typing.view.draft).toBe("sk-ant-api03-x");
    const rejected = settingsKey(typing.view, ENTER);
    expect(rejected.effect).toBeUndefined();
    expect(rejected.view.error).toBe(TOKEN_HINT);
    const cancelled = settingsKey(rejected.view, ESC);
    expect(cancelled.view.draft).toBeNull();
    const pasted = settingsKey(
      cancelled.view,
      `\u001b[200~ ${TOKEN}\n\u001b[201~`,
    );
    const saved = settingsKey(pasted.view, ENTER);
    expect(saved.effect).toEqual({ kind: "saveToken", token: TOKEN });
    expect(saved.view).toMatchObject({ hasToken: true, draft: null });
  });

  it("removes the saved token from its own row and closes on Esc", () => {
    const start = settingsView(true, true);
    const onRemove = settingsKey(settingsKey(start, DOWN).view, DOWN).view;
    const removed = settingsKey(onRemove, ENTER);
    expect(removed.effect).toEqual({ kind: "clearToken" });
    expect(removed.view.hasToken).toBe(false);
    expect(settingsKey(removed.view, ESC).effect).toEqual({ kind: "close" });
  });
});
