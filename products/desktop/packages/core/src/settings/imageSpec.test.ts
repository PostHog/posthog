import { IMAGE_TOOLS_ENV_KEY } from "@posthog/shared/constants";
import { describe, expect, it } from "vitest";
import {
  IMAGE_PRESET_TOOLS,
  type ImagePresetTool,
  SETUP_COMMAND_SUGGESTIONS,
  toolInstallMethod,
} from "./imagePreset";
import {
  buildImageSpec,
  imageSpecError,
  imageSpecToYaml,
  setupCommandError,
} from "./imageSpec";

const aptTools = IMAGE_PRESET_TOOLS.filter(
  (tool) => (tool.aptPackages?.length ?? 0) > 0,
);
const builderTool = IMAGE_PRESET_TOOLS.find(
  (tool) => (tool.aptPackages?.length ?? 0) === 0,
) as ImagePresetTool;

describe("setupCommandError", () => {
  it.each([
    ["pnpm install --frozen-lockfile", null],
    ["", "Enter a command or remove the line."],
    ["a\nb", "One line per command. Chain steps with &&."],
  ] as const)("%j", (command, expected) => {
    expect(setupCommandError(command)).toBe(expected);
  });

  it("rejects a command past the length cap", () => {
    expect(setupCommandError("x".repeat(5000))).toMatch(/4096 characters/);
  });
});

describe("imageSpecError", () => {
  it("passes for tools plus commands with a repository", () => {
    expect(
      imageSpecError({
        tools: aptTools,
        setupCommands: ["pnpm install"],
        repository: "posthog/posthog",
      }),
    ).toBeNull();
  });

  it("requires something to install", () => {
    expect(
      imageSpecError({ tools: [], setupCommands: [], repository: null }),
    ).toMatch(/at least one tool/);
  });

  it("requires a repository for setup commands, since they run in a checkout", () => {
    expect(
      imageSpecError({
        tools: aptTools,
        setupCommands: ["pnpm install"],
        repository: null,
      }),
    ).toMatch(/pick a repository/);
  });

  it("surfaces a bad command", () => {
    expect(
      imageSpecError({
        tools: aptTools,
        setupCommands: ["cd foo\nmake"],
        repository: "posthog/posthog",
      }),
    ).toMatch(/One line per command/);
  });
});

describe("buildImageSpec", () => {
  it("collects packages and commands, dropping duplicates", () => {
    const spec = buildImageSpec({
      tools: [...aptTools, ...aptTools],
      setupCommands: [" pnpm install ", ""],
      repository: "posthog/posthog",
    });
    expect(spec.apt_packages).toEqual(
      aptTools.flatMap((tool) => tool.aptPackages ?? []),
    );
    expect(spec.run_commands).toEqual([
      ...new Set(aptTools.flatMap((tool) => tool.runCommands ?? [])),
    ]);
    expect(spec.repo_setup_commands).toEqual(["pnpm install"]);
  });

  it("drops setup commands without a repository to run them in", () => {
    const spec = buildImageSpec({
      tools: aptTools,
      setupCommands: ["pnpm install"],
      repository: null,
    });
    expect(spec.repo_setup_commands).toEqual([]);
  });

  it("installs a non-apt tool with mise, and links it onto PATH", () => {
    const spec = buildImageSpec({
      tools: [builderTool],
      setupCommands: [],
      repository: null,
    });
    expect(spec.apt_packages).toEqual([]);
    expect(spec.run_commands[0]).toContain("sha256sum -c -");
    expect(spec.run_commands[0]).toMatch(
      /releases\/download\/v[\d.]+\/mise-v[\d.]+-linux-"\$MISE_ARCH"\.tar\.gz/,
    );
    expect(spec.run_commands[0]).toContain("x86_64) MISE_ARCH=x64");
    expect(spec.run_commands[0]).toContain("aarch64|arm64) MISE_ARCH=arm64");
    expect(spec.run_commands[1]).toContain("mise use -g -y");
    expect(spec.run_commands[1]).toContain(
      `/usr/local/bin/${builderTool.command}`,
    );
  });

  it("bootstraps mise once, however many tools need it", () => {
    const miseTools = IMAGE_PRESET_TOOLS.filter(
      (tool) => (tool.aptPackages?.length ?? 0) === 0,
    ).slice(0, 3);
    const spec = buildImageSpec({
      tools: miseTools,
      setupCommands: [],
      repository: null,
    });
    const bootstraps = spec.run_commands.filter((command) =>
      command.includes("install -m 0755 /tmp/mise/bin/mise"),
    );
    expect(bootstraps).toHaveLength(1);
    expect(spec.run_commands).toHaveLength(1 + miseTools.length);
  });

  it("leaves mise out entirely when apt carries everything", () => {
    const spec = buildImageSpec({
      tools: aptTools,
      setupCommands: [],
      repository: null,
    });
    expect(spec.run_commands.some((command) => command.includes("mise"))).toBe(
      false,
    );
  });
});

describe("tool pinning", () => {
  it("pins a version for every tool apt does not carry", () => {
    const unpinned = IMAGE_PRESET_TOOLS.filter(
      (tool) => toolInstallMethod(tool) === "mise",
    ).filter((tool) => !tool.version);
    expect(unpinned.map((tool) => tool.id)).toEqual([]);
  });

  it("never emits an unpinned mise install", () => {
    const spec = buildImageSpec({
      tools: IMAGE_PRESET_TOOLS,
      setupCommands: [],
      repository: null,
    });
    const unpinned = spec.run_commands.filter((command) =>
      command.includes("@latest"),
    );
    expect(unpinned).toEqual([]);
  });

  it("offers no setup command that resolves a version at build time", () => {
    // A rebuild re-runs these commands, so a `latest` toolchain lands a
    // different runtime without any repository change.
    const unpinned = SETUP_COMMAND_SUGGESTIONS.filter((suggestion) =>
      suggestion.command.includes("@latest"),
    );
    expect(unpinned.map((suggestion) => suggestion.id)).toEqual([]);
  });
});

describe("buildImageSpec env", () => {
  it("publishes the tools it installed, so the agent is told about them", () => {
    const spec = buildImageSpec({
      tools: aptTools,
      setupCommands: [],
      repository: null,
    });
    expect(spec.env[IMAGE_TOOLS_ENV_KEY]?.split(" ")).toEqual(
      aptTools.map((tool) => tool.command),
    );
    expect(imageSpecToYaml(spec)).toContain(`  ${IMAGE_TOOLS_ENV_KEY}: '`);
  });
});

describe("imageSpecToYaml", () => {
  it("writes only the lists that have entries, with quoted values", () => {
    expect(
      imageSpecToYaml({
        apt_packages: ["ripgrep"],
        run_commands: [],
        repo_setup_commands: ["pnpm install --frozen-lockfile"],
        env: {},
      }),
    ).toBe(
      [
        "apt_packages:",
        "  - 'ripgrep'",
        "repo_setup_commands:",
        "  - 'pnpm install --frozen-lockfile'",
      ].join("\n"),
    );
  });

  it("escapes a quote so the YAML stays parseable", () => {
    expect(
      imageSpecToYaml({
        apt_packages: [],
        run_commands: ["echo 'hi'"],
        repo_setup_commands: [],
        env: {},
      }),
    ).toBe(["run_commands:", "  - 'echo ''hi'''"].join("\n"));
  });
});
