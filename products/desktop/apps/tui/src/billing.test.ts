import { describe, expect, it } from "vitest";
import {
  BILLINGS,
  billingSheet,
  cloudHarnessFor,
  localStartFor,
} from "./billing";

describe("billing", () => {
  it.each([
    ["posthog", "pi"],
    ["chatgpt", "codex"],
    ["anthropic", "claude"],
  ] as const)("runs a %s cloud chat on %s", (billing, harness) => {
    expect(cloudHarnessFor(billing)).toBe(harness);
  });

  it("starts a local chat on pi, on the ChatGPT model when that plan pays", () => {
    expect(localStartFor("posthog", { chatgptAccount: null })).toEqual({});
    expect(
      localStartFor("chatgpt", { chatgptAccount: "me@example.com" }),
    ).toEqual({ model: "openai-codex/gpt-5.5" });
  });

  it("names what blocks a local chat", () => {
    expect(() => localStartFor("chatgpt", { chatgptAccount: null })).toThrow(
      "Log in to ChatGPT in settings (Ctrl+;), or pick another /billing",
    );
    expect(() => localStartFor("anthropic", { chatgptAccount: null })).toThrow(
      "Claude plan chats run in the cloud for now: type /cloud",
    );
  });

  it("offers every billing with the current one marked", () => {
    const sheet = billingSheet("chatgpt");
    expect(sheet.items.map((item) => item.current)).toEqual(
      BILLINGS.map((billing) => billing === "chatgpt"),
    );
    expect(sheet.items[2].label).toBe("Anthropic");
  });
});
