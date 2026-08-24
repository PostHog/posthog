/**
 * The starting toolset for a cost-management custom sandbox image, and the
 * brief that seeds the builder session.
 *
 * Every entry is a tool an agent commonly reaches for, chosen because it either
 * returns less text than the default it replaces or removes a per-run install.
 * Each reason states what the tool does. None of them claims a savings figure.
 *
 * `aptPackages` is how the tool gets onto the image. A tool apt carries (plus
 * at most a symlink) can be written straight into a spec and built. The rest
 * need a multi-step install that has to be verified inside the image, which is
 * what the builder session is for.
 */

/** How the list is grouped, so a long catalog stays scannable. */
export type ImageToolCategory =
  | "search"
  | "data"
  | "web"
  | "code"
  | "shell"
  | "media"
  | "platform";

export const IMAGE_TOOL_CATEGORIES: {
  id: ImageToolCategory;
  label: string;
}[] = [
  { id: "search", label: "Search and navigation" },
  { id: "data", label: "Structured data" },
  { id: "web", label: "Reading web pages and documents" },
  { id: "code", label: "Reading and changing code" },
  { id: "shell", label: "Shell and network" },
  { id: "media", label: "Screenshots and video" },
  { id: "platform", label: "Repository platform" },
];

export interface ImagePresetTool {
  id: string;
  category: ImageToolCategory;
  /** The command as typed, so the list reads like the shell it lands in. */
  command: string;
  name: string;
  /** One line, present tense, on what having it changes. */
  reason: string;
  /** Where the tool is documented, so a name can be checked before it is picked. */
  url: string;
  /** Rough installed size, so a long list's cost on the image stays visible. */
  sizeMb: number;
  /** Debian packages that install it, when apt carries it. */
  aptPackages?: string[];
  /** Single-line commands run after the packages, e.g. a symlink. */
  runCommands?: string[];
  /** mise registry name, when it differs from this tool's id. */
  miseTool?: string;
  /**
   * Exact version to install, for anything not carried by apt. Unpinned means
   * a rebuild can pull different code than the build before it, so the version
   * is part of the catalog rather than resolved at build time.
   */
  version?: string;
}

/** How the tool gets onto the image. */
export type ToolInstallMethod = "apt" | "script" | "mise";

/**
 * apt when Debian carries it, the tool's own commands when it brings them, and
 * mise for the rest. Order matters: a tool that ships an install script is not
 * in mise's registry, and asking mise for it fails the whole build.
 */
export function toolInstallMethod(tool: ImagePresetTool): ToolInstallMethod {
  if ((tool.aptPackages?.length ?? 0) > 0) return "apt";
  if ((tool.runCommands?.length ?? 0) > 0) return "script";
  return "mise";
}

/**
 * The tools an image starts with: the four an agent reaches for on nearly every
 * run. Everything else in the catalog is opt-in, so a new image stays small
 * unless someone asks for more.
 */
export const DEFAULT_TOOL_IDS: readonly string[] = [
  "ripgrep",
  "fd",
  "jq",
  "tree",
];

/** A tool the wizard can write into a spec without a builder session. */
export function isDirectlyInstallable(tool: ImagePresetTool): boolean {
  return (tool.aptPackages?.length ?? 0) > 0;
}

/** The image size the picked tools add, for the footer's running total. */
export function toolsSizeMb(tools: readonly ImagePresetTool[]): number {
  return tools.reduce((total, tool) => total + tool.sizeMb, 0);
}

export const IMAGE_PRESET_TOOLS: readonly ImagePresetTool[] = [
  {
    id: "ripgrep",
    category: "search",
    command: "rg",
    name: "ripgrep",
    url: "https://github.com/BurntSushi/ripgrep",
    sizeMb: 5,
    reason: "Faster search, and it respects gitignore",
    aptPackages: ["ripgrep"],
  },
  {
    id: "fd",
    category: "search",
    command: "fd",
    name: "fd",
    url: "https://github.com/sharkdp/fd",
    sizeMb: 3,
    reason: "Finds files by name without a find expression",
    aptPackages: ["fd-find"],
    runCommands: ["ln -sf $(command -v fdfind) /usr/local/bin/fd"],
  },
  {
    id: "jq",
    category: "data",
    command: "jq",
    name: "jq",
    url: "https://jqlang.github.io/jq/",
    sizeMb: 1,
    reason: "Reads one field out of a JSON response",
    aptPackages: ["jq"],
  },
  {
    id: "tree",
    category: "search",
    command: "tree",
    name: "tree",
    url: "https://gitlab.com/OldManProgrammer/unix-tree",
    sizeMb: 1,
    reason: "Shows a directory's shape in one call",
    aptPackages: ["tree"],
  },
  {
    id: "w3m",
    category: "web",
    command: "w3m",
    name: "w3m",
    url: "https://github.com/tats/w3m",
    sizeMb: 4,
    reason: "Renders a saved HTML page as text, so markup stays out of context",
    aptPackages: ["w3m"],
  },
  {
    id: "pandoc",
    category: "web",
    command: "pandoc",
    name: "Pandoc",
    url: "https://pandoc.org",
    sizeMb: 130,
    reason: "Converts HTML, docx and rst to Markdown in one call",
    aptPackages: ["pandoc"],
  },
  {
    id: "pdftotext",
    category: "web",
    command: "pdftotext",
    name: "Poppler utils",
    url: "https://poppler.freedesktop.org",
    sizeMb: 2,
    reason: "Reads a PDF as text, which the agent otherwise cannot open",
    aptPackages: ["poppler-utils"],
  },
  {
    id: "shellcheck",
    category: "code",
    command: "shellcheck",
    name: "ShellCheck",
    url: "https://www.shellcheck.net",
    sizeMb: 20,
    reason: "Finds shell bugs without running the script",
    aptPackages: ["shellcheck"],
  },
  {
    id: "ctags",
    category: "code",
    command: "ctags",
    name: "Universal Ctags",
    url: "https://github.com/universal-ctags/ctags",
    sizeMb: 4,
    reason: "Finds where a symbol is defined without reading the file",
    aptPackages: ["universal-ctags"],
    runCommands: ["ln -sf $(command -v ctags-universal) /usr/local/bin/ctags"],
  },
  {
    id: "yamllint",
    category: "code",
    command: "yamllint",
    name: "yamllint",
    url: "https://github.com/adrienverge/yamllint",
    sizeMb: 3,
    reason: "Names the line a broken manifest breaks on",
    aptPackages: ["yamllint"],
  },
  {
    id: "actionlint",
    version: "1.7.12",
    category: "code",
    command: "actionlint",
    name: "actionlint",
    url: "https://github.com/rhysd/actionlint",
    sizeMb: 6,
    reason: "Catches a broken workflow before a push waits on red CI",
  },
  {
    id: "ast-grep",
    version: "0.45.1",
    category: "code",
    command: "ast-grep",
    name: "ast-grep",
    url: "https://ast-grep.github.io",
    sizeMb: 12,
    reason: "Matches code by syntax instead of by text",
  },
  {
    id: "yq",
    version: "4.53.6",
    category: "data",
    command: "yq",
    name: "yq",
    url: "https://github.com/mikefarah/yq",
    sizeMb: 12,
    reason: "The same as jq, for YAML config and workflows",
  },
  {
    id: "sd",
    category: "code",
    command: "sd",
    name: "sd",
    url: "https://github.com/chmln/sd",
    sizeMb: 3,
    reason: "Replaces text across files without a sed expression",
    aptPackages: ["sd"],
  },
  {
    id: "miller",
    category: "data",
    command: "mlr",
    name: "Miller",
    url: "https://miller.readthedocs.io",
    sizeMb: 12,
    reason: "Queries CSV and TSV without loading it into a script",
    aptPackages: ["miller"],
  },
  {
    id: "sqlite3",
    category: "data",
    command: "sqlite3",
    name: "SQLite",
    url: "https://www.sqlite.org",
    sizeMb: 2,
    reason: "Queries the .db files a repository ships, in one call",
    aptPackages: ["sqlite3"],
  },
  {
    id: "duckdb",
    version: "1.5.5",
    category: "data",
    command: "duckdb",
    name: "DuckDB",
    url: "https://duckdb.org",
    sizeMb: 40,
    reason: "Runs SQL over a CSV, JSON or Parquet file with no import step",
  },
  {
    id: "xmllint",
    category: "data",
    command: "xmllint",
    name: "libxml2 utils",
    url: "https://gitlab.gnome.org/GNOME/libxml2",
    sizeMb: 1,
    reason: "Pulls one XPath match out of XML, and checks it parses",
    aptPackages: ["libxml2-utils"],
  },
  {
    id: "gron",
    category: "data",
    command: "gron",
    name: "gron",
    url: "https://github.com/tomnomnom/gron",
    sizeMb: 4,
    reason: "Flattens JSON into lines, so a field can be grepped",
    aptPackages: ["gron"],
  },
  {
    id: "difftastic",
    version: "0.70.0",
    category: "code",
    command: "difft",
    name: "difftastic",
    url: "https://difftastic.wilfred.me.uk",
    sizeMb: 10,
    reason: "Diffs by syntax, so a reformat is not a wall of changes",
  },
  {
    id: "moreutils",
    category: "shell",
    command: "sponge",
    name: "moreutils",
    url: "https://joeyh.name/code/moreutils/",
    sizeMb: 1,
    reason:
      "Writes a file it just read without truncating it, plus chronic, ts and parallel",
    aptPackages: ["moreutils"],
  },
  {
    id: "bsdtar",
    category: "shell",
    command: "bsdtar",
    name: "libarchive tools",
    url: "https://www.libarchive.org",
    sizeMb: 4,
    reason: "Unpacks tar, zip, 7z and iso without picking an extractor",
    aptPackages: ["libarchive-tools", "unzip", "zstd"],
  },
  {
    id: "dig",
    category: "shell",
    command: "dig",
    name: "BIND DNS utils",
    url: "https://www.isc.org/bind/",
    sizeMb: 2,
    reason: "Separates a blocked host from a wrong one in one call",
    aptPackages: ["bind9-dnsutils"],
  },
  {
    id: "xh",
    version: "0.26.2",
    category: "shell",
    command: "xh",
    name: "xh",
    url: "https://github.com/ducaale/xh",
    sizeMb: 6,
    reason: "Calls a JSON API and prints the body without the header block",
  },
  // Tools for looking at what the agent built. A browser install belongs in
  // the setup step instead: it has to match the repository's own Playwright
  // version and warm its browser cache, which only a checkout can do.
  {
    id: "playwright",
    category: "media",
    command: "playwright",
    name: "Playwright with Chromium",
    url: "https://playwright.dev/docs/browsers",
    sizeMb: 450,
    reason: "Drives a browser to screenshot and record what the agent built",
    runCommands: [
      "npm install -g playwright@1.62.1 && playwright install --with-deps chromium",
    ],
  },
  {
    id: "ffmpeg",
    category: "media",
    command: "ffmpeg",
    name: "FFmpeg",
    url: "https://ffmpeg.org/documentation.html",
    sizeMb: 240,
    reason: "Trims and converts the video a browser test recorded",
    aptPackages: ["ffmpeg"],
  },
  {
    id: "imagemagick",
    category: "media",
    command: "convert",
    name: "ImageMagick",
    url: "https://imagemagick.org/script/command-line-tools.php",
    sizeMb: 60,
    reason: "Crops and compares screenshots without writing a script",
    aptPackages: ["imagemagick"],
  },
  // Repository tools that do not depend on which host the repo lives on.
  {
    id: "gh",
    category: "platform",
    version: "2.97.0",
    command: "gh",
    name: "GitHub CLI",
    url: "https://cli.github.com",
    sizeMb: 40,
    reason: "Reads issues, pull requests and CI logs without scraping",
  },
  {
    id: "git-lfs",
    category: "platform",
    command: "git-lfs",
    name: "Git LFS",
    url: "https://git-lfs.com",
    sizeMb: 12,
    reason: "Checks out real files instead of pointer stubs",
    aptPackages: ["git-lfs"],
  },
  {
    id: "gitleaks",
    category: "platform",
    command: "gitleaks",
    name: "Gitleaks",
    url: "https://github.com/gitleaks/gitleaks",
    sizeMb: 12,
    reason: "Scans a diff for secrets offline, before anything is pushed",
    aptPackages: ["gitleaks"],
  },
  {
    id: "git-absorb",
    category: "platform",
    command: "git-absorb",
    name: "git-absorb",
    url: "https://github.com/tummychow/git-absorb",
    sizeMb: 3,
    reason: "Folds fixups into the commits they belong to, without a rebase",
    aptPackages: ["git-absorb"],
    runCommands: [
      "ln -sf /usr/lib/git-core/git-absorb /usr/local/bin/git-absorb",
    ],
  },
];

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
    .map((tool) => {
      const invocation = tool.version
        ? `${tool.command}@${tool.version}`
        : tool.command;
      return `- ${invocation} (${tool.name}): ${tool.reason}`;
    })
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

/**
 * Setup commands worth offering, since they are the ones that pay off most and
 * the easiest to get subtly wrong. They run in a checkout at build time, so a
 * browser or dependency install lands at the version the repository pins and
 * its cache is baked in.
 */
export type SetupCommandGroup = "dependencies" | "toolchains" | "project";

export const SETUP_COMMAND_GROUPS: readonly {
  id: SetupCommandGroup;
  label: string;
}[] = [
  { id: "dependencies", label: "Dependencies" },
  { id: "toolchains", label: "Toolchains" },
  { id: "project", label: "Project setup" },
];

export interface SetupCommandSuggestion {
  id: string;
  group: SetupCommandGroup;
  label: string;
  command: string;
  /** One line on what it buys, or what it costs. */
  note: string;
}

/**
 * Commands worth offering, one per ecosystem: the install a repository runs
 * before anything else, in the form that reads the lockfile instead of
 * resolving fresh. Tools the image can install belong in the tools step, so
 * nothing here installs a binary the catalog already carries.
 */
export const SETUP_COMMAND_SUGGESTIONS: readonly SetupCommandSuggestion[] = [
  {
    id: "pnpm",
    group: "dependencies",
    label: "Node (pnpm)",
    command: "corepack enable && pnpm install --frozen-lockfile",
    note: "Warms the pnpm store at the version packageManager pins, so a session install is a linking pass.",
  },
  {
    id: "npm",
    group: "dependencies",
    label: "Node (npm)",
    command: "npm ci --prefer-offline --no-audit",
    note: "Installs from package-lock.json only, so the build fails rather than drifting off the lockfile.",
  },
  {
    id: "uv",
    group: "dependencies",
    label: "Python (uv)",
    command: "uv sync --frozen",
    note: "Warms the uv cache from uv.lock. uv is already on the base image.",
  },
  {
    id: "poetry",
    group: "dependencies",
    label: "Python (poetry)",
    command: "poetry install --no-interaction --no-root",
    note: "For repositories on poetry.lock. Skips installing the project itself, which the checkout already has.",
  },
  {
    id: "go",
    group: "dependencies",
    label: "Go modules",
    command: "go mod download",
    note: "Fills the module cache from go.sum, which is most of a cold Go build.",
  },
  {
    id: "cargo",
    group: "dependencies",
    label: "Rust crates",
    command: "cargo fetch --locked",
    note: "Downloads every crate in Cargo.lock without building, so nothing is resolved at session start.",
  },
  {
    id: "bundler",
    group: "dependencies",
    label: "Ruby gems",
    command: "bundle install --jobs 4",
    note: "Installs the gems in Gemfile.lock, including native extensions that are slow to compile.",
  },
  {
    id: "gradle",
    group: "dependencies",
    label: "Gradle",
    command: "./gradlew --no-daemon dependencies",
    note: "Resolves and caches the dependency graph. No daemon, since the build here is one shot.",
  },
  {
    id: "maven",
    group: "dependencies",
    label: "Maven",
    command: "mvn -B -q dependency:go-offline",
    note: "Pulls everything the build needs into the local repository, so a session can build offline.",
  },
  {
    id: "composer",
    group: "dependencies",
    label: "PHP packages",
    command: "composer install --no-interaction --prefer-dist",
    note: "Installs from composer.lock and prefers prebuilt archives over cloning each package.",
  },
  {
    id: "dotnet",
    group: "dependencies",
    label: "NuGet packages",
    command: "dotnet restore",
    note: "Restores packages for every project in the solution.",
  },
  {
    id: "mise-repo",
    group: "toolchains",
    label: "Toolchains the repo pins",
    command: "mise install -y",
    note: "Installs the versions declared in .mise.toml or .tool-versions, so nothing is guessed.",
  },
  {
    id: "pre-commit",
    group: "project",
    label: "Pre-commit hooks",
    command: "pre-commit install --install-hooks",
    note: "Builds each hook's environment now, so the first commit in a session is not a five-minute wait.",
  },
];
