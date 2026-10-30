import { describe, expect, it } from "vitest";
import { settingsKey, settingsView } from "./settings";

const DOWN = "\u001b[B";
const ENTER = "\r";
const ESC = "\u001b";

describe("settingsKey", () => {
  it("toggles the ChatGPT plan with Enter on the first row", () => {
    const { view, effect } = settingsKey(settingsView(false, null), ENTER);
    expect(view.planOn).toBe(true);
    expect(effect).toEqual({ kind: "setPlan", on: true });
  });

  it("starts a login from the second row and ignores a second Enter while it runs", () => {
    const onLogin = settingsKey(settingsView(false, null), DOWN).view;
    const started = settingsKey(onLogin, ENTER);
    expect(started.effect).toEqual({ kind: "login" });
    expect(started.view.busy).toBe(true);
    expect(settingsKey(started.view, ENTER).effect).toBeUndefined();
  });

  it("answers an open prompt on Enter and cancels it on Esc", () => {
    const asked = {
      ...settingsView(false, null),
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

  it("logs out from the second row when logged in, and closes on Esc", () => {
    const onLogout = settingsKey(
      settingsView(true, "me@example.com"),
      DOWN,
    ).view;
    const out = settingsKey(onLogout, ENTER);
    expect(out.effect).toEqual({ kind: "logout" });
    expect(out.view.account).toBeNull();
    expect(settingsKey(out.view, ESC).effect).toEqual({ kind: "close" });
  });
});
