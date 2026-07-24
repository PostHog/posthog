import { describe, expect, it, vi } from "vitest";
import {
  compilePostHogExecPermissionRegex,
  DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
  extractPostHogSubTool,
  isPostHogExecDescriptor,
  isPostHogExecTool,
  matchesPostHogExecPermission,
  resolvePostHogExecPermissionRegex,
} from "./posthog-exec-permission";

const permissionRegex = compilePostHogExecPermissionRegex(
  DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
);

describe("PostHog exec identification", () => {
  it("matches bare and plugin-prefixed PostHog exec tools", () => {
    expect(isPostHogExecTool("mcp__posthog__exec")).toBe(true);
    expect(isPostHogExecTool("mcp__posthog_posthog__exec")).toBe(true);
    expect(isPostHogExecTool("mcp__posthog_cloud__exec")).toBe(true);
    expect(isPostHogExecDescriptor({ server: "posthog", tool: "exec" })).toBe(
      true,
    );
  });

  it("rejects other servers and tools", () => {
    expect(isPostHogExecTool("mcp__posthog__list")).toBe(false);
    expect(isPostHogExecTool("mcp__other__exec")).toBe(false);
    expect(isPostHogExecDescriptor({ server: "other", tool: "exec" })).toBe(
      false,
    );
  });
});

describe("extractPostHogSubTool", () => {
  it.each([
    ["call experiment-update", "experiment-update"],
    ['call --json experiment-update {"id":1}', "experiment-update"],
    ['call --confirm dashboard-update {"id":2}', "dashboard-update"],
    ['call --json --confirm dashboard-update {"id":2}', "dashboard-update"],
    ["  call foo-delete", "foo-delete"],
  ])("extracts the sub-tool from %s", (command, expected) => {
    expect(extractPostHogSubTool({ command })).toBe(expected);
  });

  it.each([
    { command: "tools" },
    { command: "search experiments" },
    { command: "info flag-get" },
    { command: "call --confirm" },
    undefined,
    null,
    {},
    { command: 42 },
    { command: "" },
  ])("returns null for non-call or malformed input", (input) => {
    expect(extractPostHogSubTool(input)).toBeNull();
  });
});

describe("configured permission regex", () => {
  it.each([
    "experiment-update",
    "feature-flag-delete",
    "notebooks-destroy",
    "experiment-partial-update",
    "feature-flag-patch",
    "UPDATE-something",
    "delete",
  ])("matches %s case-insensitively", (subTool) => {
    expect(matchesPostHogExecPermission(subTool, permissionRegex)).toBe(true);
  });

  it.each([
    "experiment-get",
    "feature-flag-list",
    "experiment-create",
    "insights-pause",
    "get-updated-events",
    "deleter-test",
  ])("does not match %s", (subTool) => {
    expect(matchesPostHogExecPermission(subTool, permissionRegex)).toBe(false);
  });

  it("rejects invalid regex source", () => {
    expect(() => compilePostHogExecPermissionRegex("[")).toThrow();
  });
});

describe("resolvePostHogExecPermissionRegex", () => {
  it.each([undefined, null])("compiles the default for %s", (value) => {
    const onInvalid = vi.fn();
    const regex = resolvePostHogExecPermissionRegex(value, onInvalid);
    expect(regex.source).toBe(
      compilePostHogExecPermissionRegex(
        DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
      ).source,
    );
    expect(onInvalid).not.toHaveBeenCalled();
  });

  it("compiles a valid custom source case-insensitively", () => {
    const regex = resolvePostHogExecPermissionRegex("(^|-)archive(-|$)");
    expect(regex.test("Dashboard-Archive")).toBe(true);
    expect(regex.test("dashboard-delete")).toBe(false);
  });

  it.each(["", "[", 42])(
    "falls back to the default and reports %j as invalid",
    (value) => {
      const onInvalid = vi.fn();
      const regex = resolvePostHogExecPermissionRegex(value, onInvalid);
      expect(regex.source).toBe(
        compilePostHogExecPermissionRegex(
          DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
        ).source,
      );
      expect(onInvalid).toHaveBeenCalledTimes(1);
    },
  );
});
