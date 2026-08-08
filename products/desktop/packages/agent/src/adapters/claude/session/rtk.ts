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
 * tracking single/double quotes, backslash escapes, and parenthesis depth so
 * operators inside quoted arguments, `$(...)`/`<(...)` substitutions, and
 * subshells don't split — a split there would put the substitution's tail in
 * its own segment, hiding the `$(` from the per-segment operator guard and
 * letting compressed output leak into text another program consumes. Returns
 * null when the line uses syntax the splitter doesn't model (unbalanced
 * quotes or parens, multiline input such as heredocs — a `;` inside a heredoc
 * body is document text, not a separator), so callers fail safe.
 */
export function splitTopLevelSegments(
  command: string,
): CommandSegment[] | null {
  if (command.includes("\n")) return null;

  const segments: CommandSegment[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  let parenDepth = 0;
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
    if (ch === "(") {
      parenDepth++;
      current += ch;
      continue;
    }
    if (ch === ")") {
      // A closer with no opener (`case x in x) …`) is syntax the splitter
      // doesn't model — fail safe rather than guess.
      if (parenDepth === 0) return null;
      parenDepth--;
      current += ch;
      continue;
    }
    if (parenDepth === 0 && ch === "&" && command[i + 1] === "&") {
      segments.push({ text: current, separator: "&&" });
      current = "";
      i++;
      continue;
    }
    if (parenDepth === 0 && ch === ";") {
      segments.push({ text: current, separator: ";" });
      current = "";
      continue;
    }
    current += ch;
  }
  if (quote || parenDepth !== 0) return null;
  segments.push({ text: current, separator: "" });
  return segments;
}

// find primaries rtk's own parser accepts (verified against rtk; it hard-fails
// with exit 1 on anything else — `-not`, `!`, `-and`, `-newer`, `-mtime`,
// `-exec`, `-delete`, …). Rewriting an unsupported invocation would replace the
// file list with an error, costing a raw retry, so only invocations whose
// every `-flag` token is in this allowlist are rewritten. Exported so the
// instruction-level Codex guidance advertises the same constraint.
export const RTK_FIND_SUPPORTED_FLAGS = new Set([
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
// matches rtk's rg filter models — compacting them would corrupt counts, file
// lists, or JSON that a consumer (or the model) reads structurally. `-h`/`-V`
// and their long forms are intercepted by rtk itself (`rtk rg -h` prints the
// wrapper's help, not ripgrep's), so they change meaning, not just shape.
const RG_UNSAFE_LONG_FLAGS = new Set([
  "--json",
  "--files",
  "--files-with-matches",
  "--files-without-match",
  "--count",
  "--count-matches",
  "--stats",
  "--pretty",
  "--quiet",
  "--replace",
  "--vimgrep",
  "--help",
  "--version",
]);
const RG_UNSAFE_SHORT_LETTERS = new Set(["l", "c", "p", "q", "r", "h", "V"]);

// rg accepts clustered short options (`-nl` contains `-l`) and `=`-attached
// long values (`--replace=x`), so the guard must normalize before matching —
// exact-token comparison is trivially bypassed by common spellings.
function hasUnsafeRgFlag(tokens: string[]): boolean {
  for (const token of tokens) {
    if (token.startsWith("--")) {
      const bare = token.split("=", 1)[0];
      if (RG_UNSAFE_LONG_FLAGS.has(bare)) return true;
    } else if (/^-[a-zA-Z]+$/.test(token)) {
      for (const letter of token.slice(1)) {
        if (RG_UNSAFE_SHORT_LETTERS.has(letter)) return true;
      }
    }
  }
  return false;
}

function findFlagTokens(trimmed: string): string[] {
  return trimmed
    .split(/\s+/)
    .slice(1)
    .map((token) => {
      const unquoted =
        (token.startsWith("'") && token.endsWith("'")) ||
        (token.startsWith('"') && token.endsWith('"'))
          ? token.slice(1, -1)
          : token;
      // `\(`/`\)`/`\!` reach find as bare grouping tokens — strip the shell
      // escape so the guard sees what find sees.
      return unquoted.startsWith("\\") ? unquoted.slice(1) : unquoted;
    });
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

export interface RtkRewriteOptions {
  /**
   * Whether `rg` is a real executable on PATH. `rtk rg` execs rg itself, so
   * it fails where rg is only a shell function (Claude Code's embedded
   * ripgrep) — those environments leave rg raw. Detected once per session via
   * `rgOnPath(env)`.
   */
  rgOnPath?: boolean;
}

export function rgOnPath(env: NodeJS.ProcessEnv): boolean {
  return findOnPath("rg", env) !== undefined;
}

/**
 * Returns the `<prefix> <cmd>` rewrite of one chain segment, or null to leave
 * it untouched. rtk's filters are explicitly lossy at scale (result caps with
 * `+N` truncation markers), so only commands rtk proxies natively — where the
 * truncation is discoverable from an uncapped total header — are rewritten;
 * a command piped anywhere (e.g. `rg … | cat`) always bypasses the rewrite,
 * which is the exact-output escape hatch.
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
    // Predicates outside rtk's parser (-not, -exec, !, …) run raw. They tend
    // to be used when the agent needs the complete matched set, and rtk's
    // pipe filters truncate large lists (10 per dir, `+N` markers) —
    // compressing there deletes exactly what the invocation exists to produce.
    if (!rtkSupportsFindInvocation(trimmed)) return null;
    return `${quotedPrefix} ${trimmed}`;
  }
  if (head === "rg") {
    // Only when rg is a real executable — `rtk rg` execs rg itself, which
    // fails where rg is a shell function (Claude Code's embedded ripgrep).
    // The rg proxy applies the same result caps as the long-shipped grep
    // proxy and reports the uncapped total ("N matches in M files"), so
    // truncation stays discoverable.
    if (!options.rgOnPath) return null;
    if (hasUnsafeRgFlag(trimmed.split(/\s+/).slice(1))) return null;
    return `${quotedPrefix} ${trimmed}`;
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
  const isWindows = process.platform === "win32";
  const exts = isWindows ? [".exe", ".cmd", ".bat", ""] : [""];
  for (const dir of pathVar.split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const full = path.join(dir, bin + ext);
      try {
        if (!fs.statSync(full).isFile()) continue;
        // The shell would skip a non-executable file and resolve the next PATH
        // entry (or a shell function); treating it as available would produce
        // rewrites that die with EACCES. Windows has no execute bit.
        if (!isWindows) fs.accessSync(full, fs.constants.X_OK);
        return full;
      } catch {
        // Not here or not executable; keep looking.
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
