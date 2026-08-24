import { IMAGE_TOOLS_ENV_KEY } from "@posthog/shared/constants";
import { type ImagePresetTool, toolInstallMethod } from "./imagePreset";

/**
 * Builds the declarative sandbox image spec the backend scans and builds.
 *
 * The rules here mirror the server's schema, so the wizard cannot produce a
 * spec the scanner rejects: commands are single-line (each becomes one
 * Dockerfile RUN, so chain with &&), apt package names are lowercase and free
 * of shell characters, repo setup commands need a repository to run in, and
 * every list is capped.
 */

const MAX_APT_PACKAGES = 128;
const MAX_RUN_COMMANDS = 64;
export const MAX_COMMAND_LENGTH = 4096;

const APT_PACKAGE_PATTERN = /^[a-z0-9][a-z0-9+.-]*$/;

export interface ImageSpec {
  apt_packages: string[];
  run_commands: string[];
  repo_setup_commands: string[];
  /** Baked into the image, so every session on it starts with these set. */
  env: Record<string, string>;
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
  if (commands.length + toolCommands(tools).length > MAX_RUN_COMMANDS) {
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
 * The mise release the bootstrap installs. Pinned to a tag with its published
 * sha256, because the image scanner rejects an unpinned download-and-execute
 * step, and a moving installer would change what a rebuild produces.
 */
const MISE_VERSION = "v2026.8.10";
/** Published sha256 per architecture, from the release's SHASUMS256.txt. */
const MISE_SHA256 = {
  x64: "e013fe11a0a9055fe78d2546baa85eba90a56e6445c431021b4fe328e6910fe2",
  arm64: "5fd8a9ffb312b47e29f642d377ad4fa9093962b47061ef5c15665086904e1046",
} as const;

/**
 * Puts mise on PATH. The archive holds `mise/bin/mise`, so a wrong layout
 * fails the build loudly rather than leaving a half-installed image.
 */
function miseBootstrapCommand(): string {
  const base = `https://github.com/jdx/mise/releases/download/${MISE_VERSION}/mise-${MISE_VERSION}-linux`;
  const resolveArch = [
    'case "$(uname -m)" in',
    `x86_64) MISE_ARCH=x64; MISE_SUM=${MISE_SHA256.x64};;`,
    `aarch64|arm64) MISE_ARCH=arm64; MISE_SUM=${MISE_SHA256.arm64};;`,
    '*) echo "mise: unsupported architecture $(uname -m)" >&2; exit 1;;',
    "esac",
  ].join(" ");
  return [
    resolveArch,
    `curl -fsSL -o /tmp/mise.tar.gz ${base}-"$MISE_ARCH".tar.gz`,
    'echo "$MISE_SUM  /tmp/mise.tar.gz" | sha256sum -c -',
    "tar -xzf /tmp/mise.tar.gz -C /tmp",
    "install -m 0755 /tmp/mise/bin/mise /usr/local/bin/mise",
    "rm -rf /tmp/mise /tmp/mise.tar.gz",
  ].join(" && ");
}

/**
 * Installs one tool with mise and links it onto PATH. mise keeps binaries
 * behind shims that a non-interactive shell never activates, so without the
 * link the tool is installed and invisible.
 */
function miseInstallCommand(tool: ImagePresetTool): string {
  const registryName = tool.miseTool ?? tool.id;
  const version = tool.version ?? "latest";
  return [
    `mise use -g -y ${registryName}@${version}`,
    `ln -sf "$(mise which ${tool.command})" /usr/local/bin/${tool.command}`,
  ].join(" && ");
}

/**
 * Every command the tools need, in build order: mise itself first, then the
 * tools it carries, then the packages' own follow-up commands.
 */
function toolCommands(tools: readonly ImagePresetTool[]): string[] {
  const miseTools = tools.filter((tool) => toolInstallMethod(tool) === "mise");
  return [
    ...(miseTools.length > 0 ? [miseBootstrapCommand()] : []),
    ...miseTools.map(miseInstallCommand),
    ...runCommandsFor(tools),
  ];
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
  const commands = tools.map((tool) => tool.command);
  return {
    apt_packages: [...new Set(aptPackagesFor(tools))],
    run_commands: [...new Set(toolCommands(tools))],
    repo_setup_commands: repository
      ? setupCommands.map((command) => command.trim()).filter(Boolean)
      : [],
    env:
      commands.length > 0
        ? { [IMAGE_TOOLS_ENV_KEY]: [...new Set(commands)].join(" ") }
        : {},
  };
}

/**
 * The spec as the YAML the build endpoint takes. Hand-written rather than via a
 * YAML library: the shape is three string lists, and every value is already
 * validated, so quoting each entry is enough.
 */
export function imageSpecToYaml(spec: ImageSpec): string {
  const lines: string[] = [];
  const block = (
    key: "apt_packages" | "run_commands" | "repo_setup_commands",
  ) => {
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
  const env = Object.entries(spec.env);
  if (env.length > 0) {
    lines.push("env:");
    for (const [key, value] of env) {
      lines.push(`  ${key}: ${quote(value)}`);
    }
  }
  return lines.join("\n");
}

/** Single-quoted YAML scalar, which needs only quote doubling. */
function quote(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}
