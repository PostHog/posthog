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

// Operators that make a segment more than one simple invocation. `&&` and `;`
// are handled by splitting into segments first; anything left over (pipes,
// redirection, background `&`, `||`, substitution) disqualifies its segment.
// Only top-level occurrences count — quoted arguments may contain anything.
function hasTopLevelOperator(segment: string): boolean {
  let quote: "'" | '"' | null = null;
  for (let i = 0; i < segment.length; i++) {
    const ch = segment[i];
    if (quote) {
      if (ch === "\\" && quote === '"') i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "\\") {
      i++;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if ("|&<>`\n".includes(ch)) return true;
    if (ch === "$" && segment[i + 1] === "(") return true;
  }
  return false;
}

// Exported so the instruction-level Codex guidance quotes the prefix the same way.
export function shQuote(value: string): string {
  if (/^[\w./-]+$/.test(value)) return value;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

interface CommandSegment {
  text: string;
  separator: string;
}

/**
 * Splits a command line into top-level segments joined by `&&` or `;`,
 * tracking single/double quotes and backslash escapes so operators inside
 * quoted arguments don't split. Returns null when the line uses syntax the
 * splitter doesn't model (unbalanced quotes), so callers fail safe.
 */
export function splitTopLevelSegments(
  command: string,
): CommandSegment[] | null {
  const segments: CommandSegment[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  for (let i = 0; i < command.length; i++) {
    const ch = command[i];
    if (quote) {
      current += ch;
      if (ch === "\\" && quote === '"' && i + 1 < command.length) {
        current += command[++i];
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }
    if (ch === "\\" && i + 1 < command.length) {
      current += ch + command[++i];
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === "&" && command[i + 1] === "&") {
      segments.push({ text: current, separator: "&&" });
      current = "";
      i++;
      continue;
    }
    if (ch === ";") {
      segments.push({ text: current, separator: ";" });
      current = "";
      continue;
    }
    current += ch;
  }
  if (quote) return null;
  segments.push({ text: current, separator: "" });
  return segments;
}

// find primaries rtk's own parser accepts (verified against rtk; it hard-fails
// with exit 1 on anything else — `-not`, `!`, `-and`, `-newer`, `-mtime`,
// `-exec`, `-delete`, …). Rewriting an unsupported invocation would replace the
// file list with an error, costing a raw retry, so only invocations whose
// every `-flag` token is in this allowlist are rewritten.
const RTK_FIND_SUPPORTED_FLAGS = new Set([
  "-name",
  "-iname",
  "-path",
  "-ipath",
  "-type",
  "-maxdepth",
  "-mindepth",
  "-print",
]);

// rg flags that change the output away from the plain file:line:content
// matches the grep pipe filter models — compacting them would corrupt counts,
// file lists, or JSON that a consumer (or the model) reads structurally.
// rg is piped (`rg … | rtk pipe -f grep`) rather than prefix-routed because
// rg is commonly a shell function (Claude Code's embedded ripgrep), which
// `rtk rg` cannot exec.
const RG_UNSAFE_FLAGS = new Set([
  "--json",
  "--files",
  "-l",
  "--files-with-matches",
  "--files-without-match",
  "-c",
  "--count",
  "--count-matches",
  "--stats",
  "-p",
  "--pretty",
  "-q",
  "--quiet",
  "-r",
  "--replace",
]);

// find actions that execute commands, write output elsewhere, or change the
// stdout format away from a plain file list. Their invocations are never
// touched: the pipe fallback's find filter would mis-summarize non-list output.
const FIND_ACTION_FLAGS = new Set([
  "-exec",
  "-execdir",
  "-ok",
  "-okdir",
  "-delete",
  "-ls",
  "-fls",
  "-print0",
  "-printf",
  "-fprint",
  "-fprint0",
  "-fprintf",
]);

function findFlagTokens(trimmed: string): string[] {
  return trimmed
    .split(/\s+/)
    .slice(1)
    .map((token) =>
      (token.startsWith("'") && token.endsWith("'")) ||
      (token.startsWith('"') && token.endsWith('"'))
        ? token.slice(1, -1)
        : token,
    );
}

function rtkSupportsFindInvocation(trimmed: string): boolean {
  for (const bare of findFlagTokens(trimmed)) {
    if (bare === "!" || bare === "(" || bare === ")") return false;
    if (bare.startsWith("-") && !RTK_FIND_SUPPORTED_FLAGS.has(bare)) {
      return false;
    }
  }
  return true;
}

function findEmitsPlainFileList(trimmed: string): boolean {
  return !findFlagTokens(trimmed).some((bare) => FIND_ACTION_FLAGS.has(bare));
}

/**
 * Compacts a command's stdout through rtk's pipe filter without rtk running
 * the command itself — for commands rtk can't exec (rg as a shell function)
 * or can't parse (find predicates outside its allowlist). The subshell scopes
 * `pipefail` so the segment's exit code is still the command's own (a bare
 * pipe would report rtk's exit and flip rg's no-match 1 to 0, breaking `&&`
 * short-circuits), and on re-entry its `|` disqualifies the segment, keeping
 * the rewrite idempotent.
 */
function pipeFallback(
  trimmed: string,
  quotedPrefix: string,
  filter: string,
): string {
  return `( set -o pipefail; ${trimmed} | ${quotedPrefix} pipe -f ${filter} )`;
}

export interface RtkRewriteOptions {
  /**
   * Whether `rg` is a real executable on PATH. Native `rtk rg` compresses far
   * harder than the pipe filter (it applies the proxy's result caps and match
   * summary) but execs rg itself, which fails when rg is only a shell
   * function (Claude Code's embedded ripgrep). Detected once per session via
   * `rgOnPath(env)`.
   */
  rgOnPath?: boolean;
}

export function rgOnPath(env: NodeJS.ProcessEnv): boolean {
  return findOnPath("rg", env) !== undefined;
}

/**
 * Returns the rewritten form of one chain segment, or null to leave it
 * untouched. Two shapes: `<prefix> <cmd>` when rtk can run the command itself,
 * and the pipeFallback subshell when only the command's stdout can be
 * compacted.
 */
function rewriteSegmentInvocation(
  segment: string,
  quotedPrefix: string,
  options: RtkRewriteOptions,
): string | null {
  const trimmed = segment.trim();
  if (!trimmed || hasTopLevelOperator(trimmed)) return null;

  // Already routed through rtk — keep the rewrite idempotent.
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
    return `${quotedPrefix} ${trimmed}`;
  }
  if (head === "find") {
    if (rtkSupportsFindInvocation(trimmed)) return `${quotedPrefix} ${trimmed}`;
    if (findEmitsPlainFileList(trimmed)) {
      return pipeFallback(trimmed, quotedPrefix, "find");
    }
    return null;
  }
  if (head === "rg") {
    const tokens = trimmed.split(/\s+/).slice(1);
    if (tokens.some((t) => RG_UNSAFE_FLAGS.has(t))) return null;
    if (options.rgOnPath) return `${quotedPrefix} ${trimmed}`;
    return pipeFallback(trimmed, quotedPrefix, "grep");
  }
  if (!RTK_PLAIN_COMMANDS.has(head)) return null;
  return `${quotedPrefix} ${trimmed}`;
}

/**
 * Returns `command` rewritten to run through the RTK binary at `rtkPrefix`, or
 * null when it isn't safe or worthwhile to rewrite. Pure and side-effect free.
 *
 * Lines chained with top-level `&&` or `;` are rewritten segment by segment:
 * each eligible segment gets the prefix, everything else runs untouched. The
 * chain operators themselves are semantics-preserving to keep — rtk proxies
 * the command unchanged and forwards its exit code, so `a && b` short-circuits
 * identically. Segments with pipes, redirection, `||`, or substitution are
 * never rewritten.
 */
export function rewriteBashForRtk(
  command: string,
  rtkPrefix: string,
  options: RtkRewriteOptions = {},
): string | null {
  const segments = splitTopLevelSegments(command);
  if (!segments) return null;

  const quotedPrefix = shQuote(rtkPrefix);
  let rewroteAny = false;
  const out = segments.map(({ text, separator }) => {
    const rewritten = rewriteSegmentInvocation(text, quotedPrefix, options);
    if (rewritten === null) return text + separator;
    rewroteAny = true;
    // Splice the rewritten invocation over the trimmed span, keeping the
    // segment's original surrounding whitespace so untouched syntax
    // (`;;`, `do`, …) round-trips byte-identically.
    const start = text.length - text.trimStart().length;
    const end = start + text.trim().length;
    return text.slice(0, start) + rewritten + text.slice(end) + separator;
  });

  return rewroteAny ? out.join("") : null;
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

export const createRtkRewriteHook = (
  rtkPrefix: string,
  logger: Logger,
  env: NodeJS.ProcessEnv = process.env,
): HookCallback => {
  const options: RtkRewriteOptions = { rgOnPath: rgOnPath(env) };
  return async (input: HookInput, _toolUseID: string | undefined) => {
    if (input.hook_event_name !== "PreToolUse") return { continue: true };
    if (input.tool_name !== "Bash") return { continue: true };

    const toolInput = input.tool_input as { command?: string } | undefined;
    const command = toolInput?.command;
    if (typeof command !== "string") return { continue: true };

    const rewritten = rewriteBashForRtk(command, rtkPrefix, options);
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
};
