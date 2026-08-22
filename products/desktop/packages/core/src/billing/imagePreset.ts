/**
 * The starting toolset for a cost-management custom sandbox image, and the
 * brief that seeds the builder session.
 *
 * Every entry is a search or output tool an agent reaches for on nearly every
 * run, chosen because it either returns less text than the default it replaces
 * or removes a per-run install. Nothing here claims a savings figure: the
 * reasons state what a tool does, not what it saves.
 *
 * `aptPackages` is how the tool gets onto the image. A tool apt carries (plus
 * at most a symlink) can be written straight into a spec and built. The rest
 * need a multi-step install that has to be verified inside the image, which is
 * what the builder session is for.
 */

export interface ImagePresetTool {
  id: string;
  /** The command as typed, so the list reads like the shell it lands in. */
  command: string;
  name: string;
  /** One line, present tense, on what having it changes. */
  reason: string;
  /** Debian packages that install it, when apt carries it. */
  aptPackages?: string[];
  /** Single-line commands run after the packages, e.g. a symlink. */
  runCommands?: string[];
}

/** A tool the wizard can write into a spec without a builder session. */
export function isDirectlyInstallable(tool: ImagePresetTool): boolean {
  return (tool.aptPackages?.length ?? 0) > 0;
}

export const IMAGE_PRESET_TOOLS: readonly ImagePresetTool[] = [
  {
    id: "ripgrep",
    command: "rg",
    name: "ripgrep",
    reason: "Faster search, and it respects gitignore",
    aptPackages: ["ripgrep"],
  },
  {
    id: "fd",
    command: "fd",
    name: "fd",
    reason: "Finds files by name without a find expression",
    aptPackages: ["fd-find"],
    // Debian ships the binary as fdfind to avoid a name clash.
    runCommands: ["ln -sf $(command -v fdfind) /usr/local/bin/fd"],
  },
  {
    id: "jq",
    command: "jq",
    name: "jq",
    reason: "Reads one field out of a JSON response",
    aptPackages: ["jq"],
  },
  {
    id: "tree",
    command: "tree",
    name: "tree",
    reason: "Shows a directory's shape in one call",
    aptPackages: ["tree"],
  },
  {
    id: "ast-grep",
    command: "ast-grep",
    name: "ast-grep",
    reason: "Matches code by syntax instead of by text",
  },
  {
    id: "yq",
    command: "yq",
    name: "yq",
    reason: "The same as jq, for YAML config and workflows",
  },
];

export type RepoHost = "github" | "gitlab";

/** The platform CLI matched to where the repo lives. */
export function platformCliTool(host: RepoHost): ImagePresetTool {
  if (host === "gitlab") {
    return {
      id: "glab",
      command: "glab",
      name: "GitLab CLI",
      reason: "Reads issues and merge requests without scraping web pages",
    };
  }
  return {
    id: "gh",
    command: "gh",
    name: "GitHub CLI",
    reason: "Reads issues, pull requests and CI logs without scraping",
  };
}

export function imagePresetTools(host: RepoHost): ImagePresetTool[] {
  return [...IMAGE_PRESET_TOOLS, platformCliTool(host)];
}

/** A short, human name for the image, derived from the repo it serves. */
export function imagePresetName(repository: string): string {
  const repoName = repository.split("/").pop() ?? repository;
  return `${repoName} toolchain`;
}

/**
 * The brief handed to the builder session. The builder authors and verifies the
 * spec, so this states the goal, the tools and the setup commands rather than
 * shell lines, and asks it to report anything it could not install instead of
 * silently dropping it.
 */
export function imagePresetBrief(
  repository: string | null,
  tools: readonly ImagePresetTool[],
  setupCommands: readonly string[],
): string {
  const toolLines = tools
    .map((tool) => `- ${tool.command} (${tool.name}): ${tool.reason}`)
    .join("\n");
  const target = repository ?? "our cloud runs";
  const sections = [
    `Build a sandbox image for ${target} that cloud runs can start from without a setup step.`,
    `Put these command line tools on PATH:\n\n${toolLines}`,
  ];
  if (repository) {
    const commands = setupCommands.filter((command) => command.trim() !== "");
    sections.push(
      commands.length > 0
        ? `Run these in a checkout of ${repository} so a run starts with dependencies warm:\n\n${commands.map((command) => `- ${command}`).join("\n")}`
        : `Read ${repository} to find how its dependencies are installed (lockfiles, package managers, language runtimes, browsers or system libraries the tests need) and warm them at the versions the repo pins.`,
    );
  }
  sections.push(
    "Keep the image lean: no editors, shells or interactive tools, since nobody types in it. Pin versions where the tool has a stable release channel. When something cannot be installed, leave it out and say so in your summary rather than substituting an alternative.",
  );
  return sections.join("\n\n");
}
