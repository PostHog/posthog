import * as fs from "node:fs";
import * as path from "node:path";
import type { HookCallback, HookInput } from "@anthropic-ai/claude-agent-sdk";
import type { Logger } from "../../../utils/logger";
import { gitSubcommand } from "../git-command";

/**
 * RTK (https://github.com/rtk-ai/rtk) is a CLI proxy that compresses the output
 * of common dev commands by 60-90% before it reaches the model. When RTK is
 * available we rewrite eligible `Bash` calls to run through it, so the savings
 * happen at the source — the verbose output is never generated into context.
 *
 * Used automatically when `rtk` is on PATH; set `POSTHOG_RTK=0` to opt out.
 */

// Commands RTK compresses faithfully and that have no side effects, so wrapping
// them changes only how much output reaches the model, never what runs.
// Exported so the instruction-level Codex guidance advertises the same set.
export const RTK_PLAIN_COMMANDS = new Set(["grep", "find", "ls"]);

// Git subcommands whose output is worth compressing and that RTK handles
// faithfully. The criterion is compressible output, NOT read-only: RTK never
// changes what runs, so a mutating form (`git tag -d`, `git remote add`,
// `git reflog expire`) still executes its write — its output is just shorter.
// Excludes commit/push: negligible output to compress, and the cloud
// signed-commit guard keys on a leading `git` token that `rtk git …` would hide.
// Exported so the instruction-level Codex guidance advertises the same set.
export const GIT_COMPRESSIBLE_SUBCOMMANDS = new Set([
  "status",
  "diff",
  "log",
  "show",
  "branch",
  "blame",
  "shortlog",
  "ls-files",
  "describe",
  "tag",
  "remote",
  "reflog",
  "whatchanged",
  "grep",
]);

// Any shell control operator means the line is more than one simple invocation;
// wrapping only its head would change the meaning of the rest.
const SHELL_OPERATORS = /[|&;<>`\n]|\$\(/;

// Exported so the instruction-level Codex guidance quotes the prefix the same way.
export function shQuote(value: string): string {
  if (/^[\w./-]+$/.test(value)) return value;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/**
 * Returns `command` rewritten to run through the RTK binary at `rtkPrefix`, or
 * null when it isn't safe or worthwhile to rewrite. Pure and side-effect free.
 */
export function rewriteBashForRtk(
  command: string,
  rtkPrefix: string,
): string | null {
  const trimmed = command.trim();
  if (!trimmed || SHELL_OPERATORS.test(trimmed)) return null;

  // Already routed through rtk — keep the rewrite idempotent.
  const quotedPrefix = shQuote(rtkPrefix);
  if (
    trimmed === quotedPrefix ||
    trimmed.startsWith(`${quotedPrefix} `) ||
    trimmed.startsWith("rtk ")
  ) {
    return null;
  }

  const head = trimmed.split(/\s+/, 1)[0];
  if (head === "git") {
    const sub = gitSubcommand(trimmed);
    if (!sub || !GIT_COMPRESSIBLE_SUBCOMMANDS.has(sub)) return null;
  } else if (!RTK_PLAIN_COMMANDS.has(head)) {
    return null;
  }

  return `${quotedPrefix} ${trimmed}`;
}

function findOnPath(bin: string, env: NodeJS.ProcessEnv): string | undefined {
  const pathVar = env.PATH ?? env.Path ?? "";
  const exts =
    process.platform === "win32" ? [".exe", ".cmd", ".bat", ""] : [""];
  for (const dir of pathVar.split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const full = path.join(dir, bin + ext);
      try {
        if (fs.statSync(full).isFile()) return full;
      } catch {
        // Not in this dir; keep looking.
      }
    }
  }
  return undefined;
}

/**
 * Resolves the RTK binary to route shell output through. Auto-detects `rtk` on
 * PATH by default, so an installed `rtk` is used automatically. `POSTHOG_RTK`
 * overrides:
 *   unset / "" / "1" / "true" → auto-detect `rtk` on PATH
 *   "0" / "false"             → disabled (opt out)
 *   any other value           → an explicit path to the binary
 */
export function resolveRtkPrefix(env: NodeJS.ProcessEnv): string | undefined {
  const raw = env.POSTHOG_RTK?.trim();
  const lowered = raw?.toLowerCase();

  // Explicit opt-out, even when rtk is installed.
  if (lowered === "0" || lowered === "false") return undefined;

  // An explicit binary-path override (anything other than a bare enable flag).
  if (raw && lowered !== "1" && lowered !== "true") {
    try {
      if (fs.statSync(raw).isFile()) return raw;
    } catch {
      // Explicit path doesn't exist — treat as disabled rather than emit a
      // command that would fail with "rtk: not found".
    }
    return undefined;
  }

  // Default (unset) or explicit enable: use rtk if it is on PATH.
  return findOnPath("rtk", env);
}

/**
 * Detects the rtk binary a session on this host could use. The on/off flag
 * values of POSTHOG_RTK ("0"/"false"/"1"/"true"/unset) all mean auto-detect
 * here, so the answer reflects installation, not the per-session toggle a
 * previous session may have left in the environment. An explicit binary-path
 * override mirrors the resolver: honored when it exists, otherwise no binary.
 */
export function detectRtkBinary(env: NodeJS.ProcessEnv): string | undefined {
  const raw = env.POSTHOG_RTK?.trim();
  const lowered = raw?.toLowerCase();
  const isFlagValue =
    !raw || ["0", "false", "1", "true"].includes(lowered ?? "");
  if (!isFlagValue && raw) {
    try {
      if (fs.statSync(raw).isFile()) return raw;
    } catch {
      // Explicit path doesn't exist — sessions would get no rtk either.
    }
    return undefined;
  }
  return findOnPath("rtk", env);
}

export const createRtkRewriteHook =
  (rtkPrefix: string, logger: Logger): HookCallback =>
  async (input: HookInput, _toolUseID: string | undefined) => {
    if (input.hook_event_name !== "PreToolUse") return { continue: true };
    if (input.tool_name !== "Bash") return { continue: true };

    const toolInput = input.tool_input as { command?: string } | undefined;
    const command = toolInput?.command;
    if (typeof command !== "string") return { continue: true };

    const rewritten = rewriteBashForRtk(command, rtkPrefix);
    if (!rewritten) return { continue: true };

    logger.info(`[RtkRewriteHook] Rewriting: ${command} → ${rewritten}`);
    return {
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse" as const,
        updatedInput: { ...toolInput, command: rewritten },
      },
    };
  };
