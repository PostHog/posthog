import {
  GIT_COMPRESSIBLE_SUBCOMMANDS,
  RTK_PLAIN_COMMANDS,
  resolveRtkPrefix,
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
 * The advertised command set and rules mirror the Claude hook exactly
 * (RTK_PLAIN_COMMANDS + GIT_COMPRESSIBLE_SUBCOMMANDS, bare invocations only,
 * never commit/push), so token-usage cohorts stay comparable across adapters.
 */
export function buildRtkGuidance(rtkPrefix: string): string {
  // Same quoting as the Claude rewrite hook: a resolved path containing
  // spaces must stay one shell token in the commands the model copies.
  const prefix = shQuote(rtkPrefix);
  const plainCommands = [...RTK_PLAIN_COMMANDS].join("`, `");
  const gitSubcommands = [...GIT_COMPRESSIBLE_SUBCOMMANDS].join(", ");

  return `## rtk command-output compression

\`${prefix}\` is installed. It runs a command unchanged and compresses its output before you read it, so prefixed commands cost far less context. When you execute one of these as a single, bare command, prefix it with \`${prefix}\`:

- \`${plainCommands}\`
- these git subcommands: ${gitSubcommands}

Examples: \`${prefix} git status\`, \`${prefix} grep -rn "foo" src\`, \`${prefix} ls -la\`.

Rules:
- Only prefix a single bare invocation. Never use it when the command is part of a pipe, uses \`&&\`, \`;\`, or redirection, or when another program parses the output — compression would corrupt what the consumer reads.
- Never prefix \`git commit\`, \`git push\`, or any other command not listed above.
- Skip the prefix when you need the exact, complete output (for example, copying a diff verbatim).`;
}

/**
 * Appends the RTK guidance to Codex developer instructions when an RTK binary
 * is usable. Gated on `resolveRtkPrefix` — not `detectRtkBinary` — so the
 * per-run `POSTHOG_RTK=0` opt-out (the cloud kill-switch flag) disables the
 * guidance along with everything else.
 */
export function appendRtkGuidanceForCodex(
  instructions: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const rtkPrefix = resolveRtkPrefix(env);
  if (!rtkPrefix) return instructions;
  return [instructions, buildRtkGuidance(rtkPrefix)]
    .filter(Boolean)
    .join("\n\n");
}
