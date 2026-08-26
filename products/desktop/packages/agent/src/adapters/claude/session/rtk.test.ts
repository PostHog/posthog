import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { HookInput } from "@anthropic-ai/claude-agent-sdk";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import type { Logger } from "../../../utils/logger";
import {
  createRtkRewriteHook,
  detectRtkBinary,
  resolveRtkPrefix,
  rewriteBashForRtk,
} from "./rtk";

describe("rewriteBashForRtk", () => {
  test.each([
    // Read-only git subcommands are wrapped.
    ["git status", "rtk git status"],
    ["git diff --stat", "rtk git diff --stat"],
    ["git log --oneline -10", "rtk git log --oneline -10"],
    ["git show HEAD", "rtk git show HEAD"],
    // Plain read-only commands are wrapped.
    ["grep -rn foo src", "rtk grep -rn foo src"],
    ["find . -name '*.ts'", "rtk find . -name '*.ts'"],
    ["ls -la", "rtk ls -la"],
  ])("wraps %j", (input, expected) => {
    expect(rewriteBashForRtk(input, "rtk")).toBe(expected);
  });

  test.each([
    // Side-effecting git subcommands are left alone (also protects the
    // cloud signed-commit guard, which keys on a leading `git`).
    ["git commit -m wip"],
    ["git push origin main"],
    ["git checkout -b feature"],
    // The cloud signed-commit flow instructs the model to run these raw:
    // staging before git_signed_commit, and the stale-checkout / rebase
    // recovery sequence. They must never enter the compressible allowlist.
    ["git add -A"],
    ["git stash --include-untracked"],
    ["git stash pop"],
    ["git fetch origin main"],
    ["git reset --hard origin/main"],
    ["git rebase --continue"],
    ["git merge origin/master"],
    ["git cherry-pick abc123"],
    // Commands RTK isn't wrapping in this cut.
    ["npm test"],
    ["cat file.ts"],
    ["echo hello"],
    // Shell operators mean more than one invocation — never rewrite.
    ["git status | grep foo"],
    ["git status && ls"],
    ["grep foo src > out.txt"],
    ["ls; pwd"],
    ["echo $(git status)"],
    // A leading env assignment or explicit path is not a bare allowlisted head.
    ["FOO=bar git status"],
    ["/usr/bin/git status"],
    // Empty / whitespace.
    [""],
    ["   "],
  ])("leaves %j unchanged", (input) => {
    expect(rewriteBashForRtk(input, "rtk")).toBeNull();
  });

  test("is idempotent — does not double-wrap", () => {
    expect(rewriteBashForRtk("rtk git status", "rtk")).toBeNull();
  });

  test("shell-quotes a binary path containing spaces", () => {
    expect(rewriteBashForRtk("git status", "/Apps/My Tools/rtk")).toBe(
      "'/Apps/My Tools/rtk' git status",
    );
  });

  test("is idempotent for a space-containing prefix (quoted round-trip)", () => {
    const prefix = "/Apps/My Tools/rtk";
    const wrapped = rewriteBashForRtk("git status", prefix);
    expect(wrapped).toBe("'/Apps/My Tools/rtk' git status");
    // Feeding our own quoted output back through must not double-wrap, even
    // though the quoted first token never equals the bare prefix.
    expect(rewriteBashForRtk(wrapped as string, prefix)).toBeNull();
  });
});

describe("resolveRtkPrefix", () => {
  let dir: string;
  let binary: string;

  beforeAll(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "rtk-test-"));
    binary = path.join(dir, "rtk");
    fs.writeFileSync(binary, "#!/bin/sh\n");
  });

  afterAll(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  test.each([
    ["unset", undefined],
    ["empty", ""],
    ["1", "1"],
    ["true", "true"],
  ])("auto-detects rtk on PATH when POSTHOG_RTK is %s", (_label, value) => {
    expect(resolveRtkPrefix({ POSTHOG_RTK: value, PATH: dir })).toBe(binary);
  });

  test("returns undefined when rtk is not on PATH", () => {
    expect(resolveRtkPrefix({ PATH: "/nonexistent" })).toBeUndefined();
  });

  test.each([
    ["zero", "0"],
    ["false", "false"],
    ["FALSE", "FALSE"],
  ])(
    "opts out when POSTHOG_RTK is %s, even with rtk on PATH",
    (_label, value) => {
      expect(
        resolveRtkPrefix({ POSTHOG_RTK: value, PATH: dir }),
      ).toBeUndefined();
    },
  );

  test("uses an explicit path that exists", () => {
    expect(resolveRtkPrefix({ POSTHOG_RTK: binary })).toBe(binary);
  });

  test("is disabled for an explicit path that does not exist", () => {
    expect(
      resolveRtkPrefix({ POSTHOG_RTK: path.join(dir, "missing") }),
    ).toBeUndefined();
  });
});

describe("detectRtkBinary", () => {
  let dir: string;
  let binary: string;

  beforeAll(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "rtk-detect-"));
    binary = path.join(dir, "rtk");
    fs.writeFileSync(binary, "#!/bin/sh\n");
  });

  afterAll(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  // The per-session toggle must not hide an installed binary from the
  // status probe — a prior session leaving POSTHOG_RTK=0 in the process
  // env would otherwise flap the settings hint.
  test.each([
    ["unset", undefined],
    ["0", "0"],
    ["false", "false"],
    ["1", "1"],
    ["true", "true"],
  ])("finds the PATH binary when POSTHOG_RTK is %s", (_label, value) => {
    expect(detectRtkBinary({ POSTHOG_RTK: value, PATH: dir })).toBe(binary);
  });

  test("reports no binary when rtk is not on PATH", () => {
    expect(detectRtkBinary({ PATH: "/nonexistent" })).toBeUndefined();
  });

  test("honors an explicit path override that exists", () => {
    expect(detectRtkBinary({ POSTHOG_RTK: binary, PATH: "/nonexistent" })).toBe(
      binary,
    );
  });

  test("reports no binary for a broken explicit path, matching the resolver", () => {
    expect(
      detectRtkBinary({ POSTHOG_RTK: path.join(dir, "missing"), PATH: dir }),
    ).toBeUndefined();
  });
});

describe("createRtkRewriteHook", () => {
  const logger = {
    info() {},
    warn() {},
    error() {},
    debug() {},
  } as unknown as Logger;

  const bashInput = (command: string): HookInput =>
    ({
      session_id: "s",
      transcript_path: "/tmp/t",
      cwd: "/tmp",
      hook_event_name: "PreToolUse",
      tool_name: "Bash",
      tool_input: { command },
    }) as unknown as HookInput;

  test("rewrites an eligible Bash command to updatedInput", async () => {
    const hook = createRtkRewriteHook("rtk", logger);
    const result = await hook(bashInput("git status"), "tool-1", {
      signal: new AbortController().signal,
    });
    expect(result).toMatchObject({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        updatedInput: { command: "rtk git status" },
      },
    });
  });

  test("passes ineligible commands through untouched", async () => {
    const hook = createRtkRewriteHook("rtk", logger);
    const result = await hook(bashInput("npm test"), "tool-1", {
      signal: new AbortController().signal,
    });
    expect(result).toEqual({ continue: true });
  });

  test("ignores non-Bash tools", async () => {
    const hook = createRtkRewriteHook("rtk", logger);
    const input = {
      session_id: "s",
      transcript_path: "/tmp/t",
      cwd: "/tmp",
      hook_event_name: "PreToolUse",
      tool_name: "Read",
      tool_input: { file_path: "/x" },
    } as unknown as HookInput;
    const result = await hook(input, "tool-1", {
      signal: new AbortController().signal,
    });
    expect(result).toEqual({ continue: true });
  });
});
