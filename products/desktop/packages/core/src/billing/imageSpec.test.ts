import { describe, expect, it } from "vitest";
import { IMAGE_PRESET_TOOLS, type ImagePresetTool } from "./imagePreset";
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
    expect(spec.apt_packages).toEqual(["ripgrep", "fd-find", "jq", "tree"]);
    expect(spec.run_commands).toEqual([
      "ln -sf $(command -v fdfind) /usr/local/bin/fd",
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

  it("contributes nothing for a tool that needs the builder to install it", () => {
    const spec = buildImageSpec({
      tools: [builderTool],
      setupCommands: [],
      repository: null,
    });
    expect(spec.apt_packages).toEqual([]);
    expect(spec.run_commands).toEqual([]);
  });
});

describe("imageSpecToYaml", () => {
  it("writes only the lists that have entries, with quoted values", () => {
    expect(
      imageSpecToYaml({
        apt_packages: ["ripgrep"],
        run_commands: [],
        repo_setup_commands: ["pnpm install --frozen-lockfile"],
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
      }),
    ).toBe(["run_commands:", "  - 'echo ''hi'''"].join("\n"));
  });
});
