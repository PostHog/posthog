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
  rgOnPath,
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
    // Pipes, redirection, and substitution disqualify the segment they're in.
    ["git status | grep foo"],
    ["grep foo src > out.txt"],
    ["echo $(git status)"],
    ["git status || echo failed"],
    ["ls & wait"],
    // Chains whose segments are all ineligible stay untouched.
    ["pnpm install && pnpm test"],
    ["cd /tmp && cat file.ts"],
    // Unbalanced quotes — the splitter can't model the line, fail safe.
    ["ls 'unclosed && git status"],
    // find actions that execute, delete, or reformat output — never touched:
    // the pipe fallback's find filter would mis-summarize non-list output.
    ["find . -name '*.tmp' -exec rm {} \\;"],
    ["find . -name '*.log' -delete"],
    ["find . -type f -print0"],
    ["find . -maxdepth 1 -ls"],
    ["find . -printf '%p %s\\n'"],
    // rg output shapes the grep pipe filter would corrupt stay raw.
    ["rg --json foo src"],
    ["rg -l foo src"],
    ["rg --files src"],
    ["rg -c foo src"],
    ["rg --stats foo src"],
    // A leading env assignment or explicit path is not a bare allowlisted head.
    ["FOO=bar git status"],
    ["/usr/bin/git status"],
    // Empty / whitespace.
    [""],
    ["   "],
  ])("leaves %j unchanged", (input) => {
    expect(rewriteBashForRtk(input, "rtk")).toBeNull();
  });

  test.each([
    // Every eligible segment in a chain gets the prefix.
    ["git status && ls", "rtk git status && rtk ls"],
    ["ls; pwd", "rtk ls; pwd"],
    [
      "grep -rn foo src && git diff --stat",
      "rtk grep -rn foo src && rtk git diff --stat",
    ],
    // Ineligible segments run untouched alongside rewritten ones.
    ["cd /tmp && ls -la", "cd /tmp && rtk ls -la"],
    ["pnpm build && git status", "pnpm build && rtk git status"],
    ["git add -A && git status", "git add -A && rtk git status"],
    // A piped segment stays raw while its siblings are rewritten.
    [
      "git log --oneline | head -5; git status",
      "git log --oneline | head -5; rtk git status",
    ],
    // Operators inside quotes don't split or disqualify.
    [
      `grep -rn "a && b" src && git status`,
      `rtk grep -rn "a && b" src && rtk git status`,
    ],
    ["grep 'x;y' src", "rtk grep 'x;y' src"],
    // rtk-supported find primaries are still rewritten…
    [
      "find src -type f -name '*.ts' -maxdepth 2",
      "rtk find src -type f -name '*.ts' -maxdepth 2",
    ],
    // find predicates rtk's parser rejects but that still emit a plain file
    // list fall back to compacting stdout through rtk's pipe filter, inside a
    // pipefail subshell so the command's own exit code survives the pipe.
    [
      "find . -not -path '*/node_modules/*'",
      "( set -o pipefail; find . -not -path '*/node_modules/*' | rtk pipe -f find )",
    ],
    [
      "find . -mtime -1",
      "( set -o pipefail; find . -mtime -1 | rtk pipe -f find )",
    ],
    [
      "find . ! -name '*.md'",
      "( set -o pipefail; find . ! -name '*.md' | rtk pipe -f find )",
    ],
    // …and each find shape resolves independently inside a chain.
    [
      "find src -name '*.ts' && find . -not -path '*/dist/*'",
      "rtk find src -name '*.ts' && ( set -o pipefail; find . -not -path '*/dist/*' | rtk pipe -f find )",
    ],
    // rg runs natively (it is often a shell function rtk cannot exec) with
    // stdout compacted through the grep pipe filter.
    [
      "rg -n foo packages/agent/src",
      "( set -o pipefail; rg -n foo packages/agent/src | rtk pipe -f grep )",
    ],
    [
      "cd /tmp && rg -i pattern .",
      "cd /tmp && ( set -o pipefail; rg -i pattern . | rtk pipe -f grep )",
    ],
  ])("rewrites chained %j", (input, expected) => {
    expect(rewriteBashForRtk(input, "rtk")).toBe(expected);
  });

  test.each([
    // Native `rtk rg` compresses far harder than the pipe filter, but only
    // works when rg is a real executable rtk can exec.
    ["rg -n foo packages/agent/src", "rtk rg -n foo packages/agent/src"],
    ["cd /tmp && rg -i pattern .", "cd /tmp && rtk rg -i pattern ."],
  ])("routes rg natively when rg is on PATH: %j", (input, expected) => {
    expect(rewriteBashForRtk(input, "rtk", { rgOnPath: true })).toBe(expected);
  });

  test("unsafe rg output flags stay raw even with rg on PATH", () => {
    expect(
      rewriteBashForRtk("rg --json foo src", "rtk", { rgOnPath: true }),
    ).toBeNull();
  });

  test("chained rewrite preserves untouched-segment whitespace and `;;`", () => {
    expect(rewriteBashForRtk("case x in x) echo hi;; esac; ls", "rtk")).toBe(
      "case x in x) echo hi;; esac; rtk ls",
    );
  });

  test.each([
    ["rtk git status", "rtk"],
    ["rtk git status && rtk ls", "rtk"],
    ["( set -o pipefail; find . -mtime -1 | rtk pipe -f find )", "rtk"],
    ["( set -o pipefail; rg -n foo src | rtk pipe -f grep )", "rtk"],
  ])("is idempotent — does not double-wrap %j", (input, prefix) => {
    expect(rewriteBashForRtk(input, prefix)).toBeNull();
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

describe("rgOnPath", () => {
  let dir: string;

  beforeAll(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "rg-test-"));
    fs.writeFileSync(path.join(dir, "rg"), "#!/bin/sh\n");
  });

  afterAll(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  test("detects a real rg executable on PATH", () => {
    expect(rgOnPath({ PATH: dir })).toBe(true);
  });

  test("reports false when rg is absent (e.g. only a shell function)", () => {
    expect(rgOnPath({ PATH: "/nonexistent" })).toBe(false);
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
