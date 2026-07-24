import { describe, expect, it } from "vitest";
import { getAvailableCodexModes, getAvailableModes } from "./execution-mode";

describe("execution modes", () => {
  it("includes auto-accept permissions for claude sessions", () => {
    expect(getAvailableModes().map((mode) => mode.id)).toEqual([
      "default",
      "acceptEdits",
      "plan",
      "bypassPermissions",
      "auto",
    ]);
  });

  it("exposes the same presets as a live codex session (incl. plan)", () => {
    expect(getAvailableCodexModes().map((mode) => mode.id)).toEqual([
      "plan",
      "read-only",
      "auto",
      "full-access",
    ]);
  });
});
