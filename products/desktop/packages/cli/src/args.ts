import { realpathSync, statSync } from "node:fs";
import type { CodeExecutionMode } from "@posthog/agent/execution-mode";
import { Command, CommanderError } from "commander";

const CLI_PERMISSION_MODES = [
  "auto",
  "bypassPermissions",
] as const satisfies readonly CodeExecutionMode[];

export type CliPermissionMode = (typeof CLI_PERMISSION_MODES)[number];

export const OUTPUT_MODES = ["text", "json"] as const;

export type OutputMode = (typeof OUTPUT_MODES)[number];

export interface CliOptions {
  prompt?: string;
  cwd: string;
  permissionMode: CliPermissionMode;
  model?: string;
  systemPrompt?: string;
  output: OutputMode;
  debug: boolean;
}

export interface ParseError {
  error: string;
  exitCode: number;
}

export type ParseResult = CliOptions | ParseError;

function buildProgram(): Command {
  return new Command()
    .name("posthog-code-cli")
    .description(
      "Run one PostHog Code agent turn against a local repository and print the result",
    )
    .argument("[prompt]", "prompt for the agent (read from stdin when piped)")
    .option("--cwd <path>", "repository to run against", process.cwd())
    .option(
      "--permission-mode <mode>",
      `permission mode: ${CLI_PERMISSION_MODES.join(" | ")}`,
      "auto",
    )
    .option("--model <id>", 'Claude model id (must start with "claude-")')
    .option("--system-prompt <text>", "replace the default system prompt")
    .option(
      "--output <format>",
      `output format: ${OUTPUT_MODES.join(" | ")}`,
      "text",
    )
    .option("--debug", "verbose diagnostics on stderr", false)
    .exitOverride();
}

export function parseCliArgs(argv: string[]): ParseResult {
  const program = buildProgram();
  try {
    program.parse(argv);
  } catch (err) {
    if (err instanceof CommanderError) {
      // Help/version output was already written by commander itself.
      const informational =
        err.code === "commander.helpDisplayed" ||
        err.code === "commander.version";
      return {
        error: informational ? "" : err.message,
        exitCode: informational ? 0 : 1,
      };
    }
    throw err;
  }

  const opts = program.opts<{
    cwd: string;
    permissionMode: string;
    model?: string;
    systemPrompt?: string;
    output: string;
    debug: boolean;
  }>();

  const permissionMode = parseChoice(
    "--permission-mode",
    opts.permissionMode,
    CLI_PERMISSION_MODES,
    "; interactive modes (default, acceptEdits, plan) need a UI to answer permission prompts",
  );
  if (typeof permissionMode === "object") return permissionMode;

  const output = parseChoice("--output", opts.output, OUTPUT_MODES);
  if (typeof output === "object") return output;

  // Non-claude ids are silently coerced to the default model downstream, so
  // reject them here where the user can see why.
  if (opts.model && !opts.model.startsWith("claude-")) {
    return {
      error:
        `Invalid --model "${opts.model}". Pass a full Claude model id starting with ` +
        `"claude-" (e.g. "claude-sonnet-4-5").`,
      exitCode: 1,
    };
  }

  let cwd: string;
  try {
    // realpath: the agent SDK keys its session store by resolved path, and on
    // macOS common paths like /tmp are symlinks.
    cwd = realpathSync(opts.cwd);
    if (!statSync(cwd).isDirectory()) {
      return { error: `--cwd is not a directory: ${opts.cwd}`, exitCode: 1 };
    }
  } catch {
    return { error: `--cwd does not exist: ${opts.cwd}`, exitCode: 1 };
  }

  return {
    prompt: program.args[0],
    cwd,
    permissionMode,
    model: opts.model,
    systemPrompt: opts.systemPrompt,
    output,
    debug: opts.debug,
  };
}

function parseChoice<T extends string>(
  flag: string,
  value: string,
  allowed: readonly T[],
  hint = "",
): T | ParseError {
  if ((allowed as readonly string[]).includes(value)) {
    return value as T;
  }
  const choices = allowed.map((v) => `"${v}"`).join(" or ");
  return {
    error: `Unsupported ${flag} "${value}". Use ${choices}${hint}.`,
    exitCode: 1,
  };
}
