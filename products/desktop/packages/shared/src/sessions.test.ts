import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import {
  type AgentSession,
  resolveBypassRevertMode,
  sessionSupportsNativeSteer,
} from "./sessions";

function modeOption(
  values: string[],
  currentValue: string,
): SessionConfigOption {
  return {
    type: "select",
    id: "mode",
    name: "Mode",
    category: "mode",
    currentValue,
    options: values.map((v) => ({ name: v, value: v })),
  } as unknown as SessionConfigOption;
}

describe("resolveBypassRevertMode", () => {
  it("reverts a claude session to 'default'", () => {
    const opt = modeOption(
      ["default", "acceptEdits", "plan", "bypassPermissions"],
      "bypassPermissions",
    );
    expect(resolveBypassRevertMode(opt)).toBe("default");
  });

  it("reverts a codex session to 'auto', never the claude-only 'default'", () => {
    const opt = modeOption(
      ["plan", "read-only", "auto", "full-access"],
      "full-access",
    );
    const target = resolveBypassRevertMode(opt);
    expect(target).toBe("auto");
    expect(target).not.toBe("default");
  });

  it("falls back to the first non-bypass option when neither default nor auto exist", () => {
    expect(
      resolveBypassRevertMode(
        modeOption(["read-only", "full-access"], "full-access"),
      ),
    ).toBe("read-only");
  });

  it("returns undefined for a missing or non-select option", () => {
    expect(resolveBypassRevertMode(undefined)).toBeUndefined();
    expect(
      resolveBypassRevertMode({
        type: "boolean",
      } as unknown as SessionConfigOption),
    ).toBeUndefined();
  });
});

describe("sessionSupportsNativeSteer", () => {
  type Case = Pick<AgentSession, "isCloud" | "steering" | "adapter">;

  it.each<[string, Case, boolean]>([
    // Capability-driven: "native" folds the message into the running turn.
    [
      "claude advertises native",
      { isCloud: false, steering: "native", adapter: "claude" },
      true,
    ],
    [
      "codex app-server advertises native",
      { isCloud: false, steering: "native", adapter: "codex" },
      true,
    ],
    // codex-acp advertises "interrupt-resend" — must NOT steer natively.
    [
      "codex-acp interrupt-resend",
      { isCloud: false, steering: "interrupt-resend", adapter: "codex" },
      false,
    ],
    // Fallback: pre-capability start paths leave steering unset; never regress claude.
    [
      "claude with no capability (fallback)",
      { isCloud: false, steering: undefined, adapter: "claude" },
      true,
    ],
    [
      "codex with no capability (no fallback)",
      { isCloud: false, steering: undefined, adapter: "codex" },
      false,
    ],
    // An explicit non-native capability overrides the claude fallback.
    [
      "claude explicitly non-native",
      { isCloud: false, steering: "interrupt-resend", adapter: "claude" },
      false,
    ],
    // Cloud runs steer only when the sandbox explicitly advertises support.
    [
      "cloud claude native",
      { isCloud: true, steering: "native", adapter: "claude" },
      true,
    ],
    [
      "cloud codex native",
      { isCloud: true, steering: "native", adapter: "codex" },
      true,
    ],
    [
      "cloud without capability",
      { isCloud: true, steering: undefined, adapter: "claude" },
      false,
    ],
  ])("%s", (_label, session, expected) => {
    expect(sessionSupportsNativeSteer(session)).toBe(expected);
  });
});
