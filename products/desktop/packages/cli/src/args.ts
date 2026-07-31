import { realpathSync, statSync } from "node:fs";
import type { CodeExecutionMode } from "@posthog/agent/execution-mode";
import {
  Command,
  CommanderError,
  InvalidArgumentError,
  Option,
} from "commander";

const CLI_PERMISSION_MODES = [
  "auto",
  "bypassPermissions",
] as const satisfies readonly CodeExecutionMode[];

export type CliPermissionMode = (typeof CLI_PERMISSION_MODES)[number];

const OUTPUT_MODES = ["text", "json"] as const;

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

function parseModel(value: string): string {
  // Non-claude ids are silently coerced to the default model downstream, so
  // reject them here where the user can see why.
  if (!value.startsWith("claude-")) {
    throw new InvalidArgumentError(
      'Pass a full Claude model id starting with "claude-" (e.g. "claude-sonnet-4-5").',
    );
  }
  return value;
}

function parseCwd(value: string): string {
  // realpath: the agent SDK keys its session store by resolved path, and on
  // macOS common paths like /tmp are symlinks.
  let cwd: string;
  try {
    cwd = realpathSync(value);
  } catch {
    throw new InvalidArgumentError("No such directory.");
  }
  if (!statSync(cwd).isDirectory()) {
    throw new InvalidArgumentError("Not a directory.");
  }
  return cwd;
}

function buildProgram(): Command {
  return (
    new Command()
      .name("posthog-code-cli")
      .description(
        "Run one PostHog Code agent turn against a local repository and print the result",
      )
      .argument("[prompt]", "prompt for the agent (read from stdin when piped)")
      .option(
        "--cwd <path>",
        "repository to run against",
        parseCwd,
        realpathSync(process.cwd()),
      )
      .addOption(
        new Option(
          "--permission-mode <mode>",
          "unattended permission mode (interactive modes need a UI to answer prompts)",
        )
          .choices(CLI_PERMISSION_MODES)
          .default("auto"),
      )
      .option(
        "--model <id>",
        'Claude model id (must start with "claude-")',
        parseModel,
      )
      .option("--system-prompt <text>", "replace the default system prompt")
      .addOption(
        new Option("--output <format>", "output format")
          .choices(OUTPUT_MODES)
          .default("text"),
      )
      .option("--debug", "verbose diagnostics on stderr", false)
      .exitOverride()
      // Errors are returned as ParseError and printed once by the caller;
      // without this, commander writes them to stderr itself first.
      .configureOutput({ writeErr: () => {} })
  );
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
    permissionMode: CliPermissionMode;
    model?: string;
    systemPrompt?: string;
    output: OutputMode;
    debug: boolean;
  }>();

  return {
    prompt: program.args[0],
    cwd: opts.cwd,
    permissionMode: opts.permissionMode,
    model: opts.model,
    systemPrompt: opts.systemPrompt,
    output: opts.output,
    debug: opts.debug,
  };
}
