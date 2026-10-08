import { describe, expect, it } from "vitest";
import { settingsKey, settingsView, TOKEN_HINT } from "./settings";

const TOKEN = `sk-ant-oat01-${"x".repeat(40)}`;

const DOWN = "\u001b[B";
const ENTER = "\r";
const ESC = "\u001b";

const view = (saved: Partial<Parameters<typeof settingsView>[0]> = {}) =>
  settingsView({ billing: "posthog", account: null, ...saved });

describe("settingsKey", () => {
  it("starts a login from the first row and ignores a second Enter while it runs", () => {
    const started = settingsKey(view(), ENTER);
    expect(started.effect).toEqual({ kind: "login" });
    expect(started.view.busy).toBe(true);
    expect(settingsKey(started.view, ENTER).effect).toBeUndefined();
  });

  it("answers an open prompt on Enter and cancels it on Esc", () => {
    const asked = {
      ...view(),
      busy: true,
      prompt: "Paste the code",
      draft: "",
    };
    const typed = settingsKey(asked, "\u001b[200~ abc#xyz \u001b[201~").view;
    expect(typed.draft).toBe("abc#xyz");
    expect(settingsKey(typed, ENTER).effect).toEqual({
      kind: "answer",
      text: "abc#xyz",
    });
    expect(settingsKey(typed, ESC).effect).toEqual({ kind: "cancel" });
  });

  it("logs out from the first row when logged in, and closes on Esc", () => {
    const out = settingsKey(view({ account: "me@example.com" }), ENTER);
    expect(out.effect).toEqual({ kind: "logout" });
    expect(out.view.account).toBeNull();
    expect(settingsKey(out.view, ESC).effect).toEqual({ kind: "close" });
  });

  it("saves a pasted Claude token on Enter and rejects a bad one with a hint", () => {
    const typing = settingsKey(view(), "sk-ant-api03-x");
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

  it("removes the saved Claude token from its own row", () => {
    const onRemove = [DOWN, DOWN].reduce(
      (current, key) => settingsKey(current, key).view,
      view({ hasToken: true }),
    );
    const removed = settingsKey(onRemove, ENTER);
    expect(removed.effect).toEqual({ kind: "clearToken" });
    expect(removed.view.hasToken).toBe(false);
  });
});
