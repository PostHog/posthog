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

  it("runs claude setup-token from its row, or says to install Claude Code first", () => {
    const onRun = [DOWN, DOWN].reduce(
      (current, key) => settingsKey(current, key).view,
      view({ canSetup: true }),
    );
    const started = settingsKey(onRun, ENTER);
    expect(started.effect).toEqual({ kind: "runSetupToken" });
    expect(started.view.busy).toBe(true);
    const missing = settingsKey({ ...onRun, canSetup: false }, ENTER);
    expect(missing.effect).toBeUndefined();
    expect(missing.view.error).toContain("Install Claude Code first");
  });

  it("removes the saved Claude token from its own row", () => {
    const onRemove = [DOWN, DOWN, DOWN, DOWN].reduce(
      (current, key) => settingsKey(current, key).view,
      view({ hasToken: true }),
    );
    const removed = settingsKey(onRemove, ENTER);
    expect(removed.effect).toEqual({ kind: "clearToken" });
    expect(removed.view.hasToken).toBe(false);
  });

  it("turns the composer's context donut on and off from its own row", () => {
    const onContext = [DOWN, DOWN, DOWN, DOWN].reduce(
      (current, key) => settingsKey(current, key).view,
      view(),
    );
    const on = settingsKey(onContext, ENTER);
    expect(on.effect).toEqual({ kind: "showContext", on: true });
    expect(settingsKey(on.view, ENTER).effect).toEqual({
      kind: "showContext",
      on: false,
    });
  });

  it("hides and shows the Today briefing from its own row", () => {
    const onToday = [DOWN, DOWN, DOWN, DOWN, DOWN].reduce(
      (current, key) => settingsKey(current, key).view,
      view(),
    );
    const off = settingsKey(onToday, ENTER);
    expect(off.effect).toEqual({ kind: "showToday", on: false });
    expect(settingsKey(off.view, ENTER).effect).toEqual({
      kind: "showToday",
      on: true,
    });
  });

  it("connects ChatGPT for cloud runs from its own row, and disconnects once connected", () => {
    const onCloud = [DOWN].reduce(
      (current, key) => settingsKey(current, key).view,
      view({ account: "me@example.com" }),
    );
    const connecting = settingsKey(onCloud, ENTER);
    expect(connecting.effect).toEqual({ kind: "connectCloud" });
    expect(connecting.view.busy).toBe(true);
    expect(settingsKey(connecting.view, ENTER).effect).toBeUndefined();

    const connected = settingsKey(
      { ...onCloud, cloudAccount: "me@example.com" },
      ENTER,
    );
    expect(connected.effect).toEqual({ kind: "disconnectCloud" });
    expect(connected.view.cloudAccount).toBeNull();
  });
});
