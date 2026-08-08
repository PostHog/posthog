import {
  GIT_COMPRESSIBLE_SUBCOMMANDS,
  RTK_FIND_SUPPORTED_FLAGS,
  RTK_PLAIN_COMMANDS,
  resolveRtkPrefix,
  rgOnPath,
  shQuote,
} from "./claude/session/rtk";

/**
 * Instruction-level RTK integration for Codex sessions.
 *
 * The Claude adapter routes eligible commands through RTK deterministically
 * with a PreToolUse hook that rewrites the Bash input. Codex executes shell
 * commands internally over JSON-RPC and its app-server protocol has no
 * command-rewrite channel — the adapter can only approve or deny — so the
 * only integration point is the developer instructions: tell the model to
 * prefix eligible commands itself.
 *
 * The advertised command set and rules mirror the Claude hook (chain-segment
 * prefixing, the find predicate allowlist, rg only when it is a real PATH
 * executable, never commit/push), so token-usage cohorts stay comparable
 * across adapters.
 */
export interface RtkGuidanceOptions {
  /**
   * Whether `rg` is a real executable on PATH. `rtk rg` execs rg itself, so
   * advertising it where rg is only a shell function (Claude Code's embedded
   * ripgrep) would make every guided rg command fail.
   */
  rgOnPath?: boolean;
}

export function buildRtkGuidance(
  rtkPrefix: string,
  options: RtkGuidanceOptions = {},
): string {
  // Same quoting as the Claude rewrite hook: a resolved path containing
  // spaces must stay one shell token in the commands the model copies.
  const prefix = shQuote(rtkPrefix);
  const plainCommands = [
    ...RTK_PLAIN_COMMANDS,
    ...(options.rgOnPath ? ["rg"] : []),
  ].join("`, `");
  const gitSubcommands = [...GIT_COMPRESSIBLE_SUBCOMMANDS].join(", ");
  const findFlags = [...RTK_FIND_SUPPORTED_FLAGS].join("`, `");

  return `## rtk command-output compression

\`${prefix}\` is installed. It runs a command unchanged and compresses its output before you read it, so prefixed commands cost far less context. When you execute one of these as a bare command, prefix it with \`${prefix}\`:

- \`${plainCommands}\`
- these git subcommands: ${gitSubcommands}

Examples: \`${prefix} git status\`, \`${prefix} grep -rn "foo" src\`, \`${prefix} ls -la\`.

Rules:
- Only prefix a bare invocation. In a command chained with \`&&\` or \`;\` you may prefix each eligible sub-command individually (e.g. \`cd pkg && ${prefix} git status\`). Never prefix a command that is part of a pipe or redirection, or whose output another program parses — compression would corrupt what the consumer reads.
- Only prefix \`find\` when it uses these predicates alone: \`${findFlags}\`. Run any other find (\`-not\`, \`-exec\`, \`!\`, \`-mtime\`, …) unprefixed — rtk rejects them with an error instead of output.
- Never prefix \`git commit\`, \`git push\`, or any other command not listed above.
- Skip the prefix when you need the exact, complete output (for example, copying a diff verbatim).`;
}

/**
 * Appends the RTK guidance to Codex developer instructions when an RTK binary
 * is usable. Gated on `resolveRtkPrefix` — not `detectRtkBinary` — so the
 * per-run `POSTHOG_RTK=0` opt-out (the cloud kill-switch flag) disables the
 * guidance along with everything else. rg is advertised only when it is a
 * real executable on the host PATH, matching the Claude hook's routing check.
 */
export function appendRtkGuidanceForCodex(
  instructions: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const rtkPrefix = resolveRtkPrefix(env);
  if (!rtkPrefix) return instructions;
  return [
    instructions,
    buildRtkGuidance(rtkPrefix, { rgOnPath: rgOnPath(env) }),
  ]
    .filter(Boolean)
    .join("\n\n");
}
