import { describe, expect, it } from "vitest";
import type { CodeExecutionMode } from "../../execution-mode";
import { isToolAllowedForMode, toSdkPermissionMode } from "./tools";

describe("toSdkPermissionMode", () => {
  it("maps the custom auto mode to the SDK's default mode", () => {
    expect(toSdkPermissionMode("auto")).toBe("default");
  });

  it.each<CodeExecutionMode>([
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
  ])("passes native SDK mode %s through unchanged", (mode) => {
    expect(toSdkPermissionMode(mode)).toBe(mode);
  });
});

describe("isToolAllowedForMode stays authoritative for auto", () => {
  it.each(["Bash", "Edit", "Write", "NotebookEdit", "BashOutput", "KillShell"])(
    "auto-allows %s in auto mode",
    (tool) => {
      expect(isToolAllowedForMode(tool, "auto")).toBe(true);
    },
  );

  it.each(["Bash", "Edit", "Write"])(
    "still gates %s in default mode",
    (tool) => {
      expect(isToolAllowedForMode(tool, "default")).toBe(false);
    },
  );
});
