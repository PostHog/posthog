import { describe, expect, it } from "vitest";
import { resolveCloudInitialPermissionMode } from "./execution-modes";

describe("resolveCloudInitialPermissionMode", () => {
  it.each([
    ["codex", "auto", "auto"],
    ["codex", "read-only", "read-only"],
    ["codex", "full-access", "full-access"],
    ["codex", "plan", "plan"],
    ["codex", "default", "auto"],
    ["codex", "acceptEdits", "auto"],
    ["codex", "bypassPermissions", "full-access"],
    ["claude", "default", "default"],
    ["claude", "acceptEdits", "acceptEdits"],
    ["claude", "plan", "plan"],
    ["claude", "bypassPermissions", "bypassPermissions"],
    ["claude", "auto", "auto"],
    ["claude", "read-only", "plan"],
    ["claude", "full-access", "bypassPermissions"],
  ] as const)(
    "resolves %s adapter mode %s to %s",
    (adapter, mode, expected) => {
      expect(resolveCloudInitialPermissionMode(adapter, mode)).toBe(expected);
    },
  );
});
