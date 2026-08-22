import type { ImagePresetTool } from "./imagePreset";

/**
 * Builds the declarative sandbox image spec the backend scans and builds.
 *
 * The rules here mirror the server's schema, so the wizard cannot produce a
 * spec the scanner rejects: commands are single-line (each becomes one
 * Dockerfile RUN, so chain with &&), apt package names are lowercase and free
 * of shell characters, repo setup commands need a repository to run in, and
 * every list is capped.
 */

export const MAX_APT_PACKAGES = 128;
export const MAX_RUN_COMMANDS = 64;
export const MAX_COMMAND_LENGTH = 4096;

const APT_PACKAGE_PATTERN = /^[a-z0-9][a-z0-9+.-]*$/;

export interface ImageSpec {
  apt_packages: string[];
  run_commands: string[];
  repo_setup_commands: string[];
}

export interface ImageSpecInput {
  tools: readonly ImagePresetTool[];
  setupCommands: readonly string[];
  /** `org/repo`, or null when the image is not tied to one. */
  repository: string | null;
}

/** Why a single setup command cannot be built, or null when it is fine. */
export function setupCommandError(command: string): string | null {
  const trimmed = command.trim();
  if (trimmed === "") return "Enter a command or remove the line.";
  if (/[\r\n]/.test(command)) {
    return "One line per command. Chain steps with &&.";
  }
  if (trimmed.length > MAX_COMMAND_LENGTH) {
    return `Commands are limited to ${MAX_COMMAND_LENGTH} characters.`;
  }
  return null;
}

/** Why the spec cannot be built, or null when it is ready. */
export function imageSpecError({
  tools,
  setupCommands,
  repository,
}: ImageSpecInput): string | null {
  if (tools.length === 0 && setupCommands.length === 0) {
    return "Pick at least one tool, or add a setup command.";
  }
  const commands = setupCommands.filter((command) => command.trim() !== "");
  if (commands.length > 0 && !repository) {
    return "Setup commands run in a repository checkout, so pick a repository first.";
  }
  for (const command of commands) {
    const error = setupCommandError(command);
    if (error) return error;
  }
  if (aptPackagesFor(tools).length > MAX_APT_PACKAGES) {
    return `Images are limited to ${MAX_APT_PACKAGES} packages.`;
  }
  if (commands.length + runCommandsFor(tools).length > MAX_RUN_COMMANDS) {
    return `Images are limited to ${MAX_RUN_COMMANDS} commands.`;
  }
  return null;
}

function aptPackagesFor(tools: readonly ImagePresetTool[]): string[] {
  return tools
    .flatMap((tool) => tool.aptPackages ?? [])
    .filter((name) => APT_PACKAGE_PATTERN.test(name));
}

function runCommandsFor(tools: readonly ImagePresetTool[]): string[] {
  return tools.flatMap((tool) => tool.runCommands ?? []);
}

/**
 * The spec for the chosen tools and setup commands. Callers must check
 * `imageSpecError` first; this assumes a valid input.
 */
export function buildImageSpec({
  tools,
  setupCommands,
  repository,
}: ImageSpecInput): ImageSpec {
  return {
    apt_packages: [...new Set(aptPackagesFor(tools))],
    run_commands: [...new Set(runCommandsFor(tools))],
    repo_setup_commands: repository
      ? setupCommands.map((command) => command.trim()).filter(Boolean)
      : [],
  };
}

/**
 * The spec as the YAML the build endpoint takes. Hand-written rather than via a
 * YAML library: the shape is three string lists, and every value is already
 * validated, so quoting each entry is enough.
 */
export function imageSpecToYaml(spec: ImageSpec): string {
  const lines: string[] = [];
  const block = (key: keyof ImageSpec) => {
    const values = spec[key];
    if (values.length === 0) return;
    lines.push(`${key}:`);
    for (const value of values) {
      lines.push(`  - ${quote(value)}`);
    }
  };
  block("apt_packages");
  block("run_commands");
  block("repo_setup_commands");
  return lines.join("\n");
}

/** Single-quoted YAML scalar, which needs only quote doubling. */
function quote(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}
