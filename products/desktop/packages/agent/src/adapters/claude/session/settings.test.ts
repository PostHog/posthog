import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resolveMainRepoPath } from "./repo-path";
import { mergeAvailableModels, SettingsManager } from "./settings";

function runGit(cwd: string, args: string[]): void {
  execFileSync("git", args, { cwd, stdio: ["ignore", "ignore", "pipe"] });
}

describe("SettingsManager per-repo persistence", () => {
  let mainRepo: string;
  let worktree: string;
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await fs.promises.realpath(
      await fs.promises.mkdtemp(path.join(os.tmpdir(), "settings-manager-")),
    );
    mainRepo = path.join(tmpRoot, "main");
    worktree = path.join(tmpRoot, "wt");
    await fs.promises.mkdir(mainRepo, { recursive: true });

    runGit(mainRepo, ["init", "-b", "main"]);
    runGit(mainRepo, ["config", "user.email", "test@example.com"]);
    runGit(mainRepo, ["config", "user.name", "test"]);
    runGit(mainRepo, ["commit", "--allow-empty", "-m", "init"]);
    runGit(mainRepo, ["worktree", "add", "-b", "feat", worktree]);
  });

  afterEach(async () => {
    await fs.promises.rm(tmpRoot, { recursive: true, force: true });
  });

  it("persists allow rules to the primary worktree when invoked from a secondary worktree", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await manager.addAllowRules([
      { toolName: "Bash", ruleContent: "pnpm test:*" },
    ]);

    const repoLocalPath = path.join(mainRepo, ".claude", "settings.local.json");
    const contents = JSON.parse(
      await fs.promises.readFile(repoLocalPath, "utf-8"),
    );
    expect(contents.permissions.allow).toContain("Bash(pnpm test:*)");

    const worktreeLocalPath = path.join(
      worktree,
      ".claude",
      "settings.local.json",
    );
    expect(fs.existsSync(worktreeLocalPath)).toBe(false);
  });

  it("sees rules persisted by a sibling worktree after re-initialization", async () => {
    const writer = new SettingsManager(worktree);
    await writer.initialize();
    await writer.addAllowRules([{ toolName: "TodoWrite" }]);

    const sibling = path.join(tmpRoot, "wt2");
    runGit(mainRepo, ["worktree", "add", "-b", "other", sibling]);

    const reader = new SettingsManager(sibling);
    await reader.initialize();
    const decision = reader.checkPermission("TodoWrite", {});
    expect(decision.decision).toBe("allow");
  });

  it("widens name-based matching for argumentless rules", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await manager.addAllowRules([{ toolName: "TodoWrite" }]);

    expect(manager.checkPermission("TodoWrite", {}).decision).toBe("allow");
  });

  it("does not widen name-based matching when the rule has an argument", async () => {
    // A rule *with* an argument for a tool we don't have an accessor for must
    // not match regardless of the actual input — otherwise a deny rule like
    // `Bash(rm -rf)` applied to a non-ACP Bash invocation would match any
    // command.
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await manager.addAllowRules([
      { toolName: "UnknownTool", ruleContent: "something" },
    ]);

    expect(
      manager.checkPermission("UnknownTool", { command: "anything" }).decision,
    ).toBe("ask");
  });

  it("still allows ACP-prefixed Bash invocations when a Bash(...) rule is persisted", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await manager.addAllowRules([
      { toolName: "Bash", ruleContent: "pnpm test:*" },
    ]);

    const decision = manager.checkPermission("mcp__acp__Bash", {
      command: "pnpm test --filter agent",
    });
    expect(decision.decision).toBe("allow");
  });

  it("refuses to overwrite the file when existing contents cannot be parsed", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    const filePath = path.join(mainRepo, ".claude", "settings.local.json");
    const original = "{ this is not valid json";
    await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
    await fs.promises.writeFile(filePath, original);

    await expect(
      manager.addAllowRules([{ toolName: "TodoWrite" }]),
    ).rejects.toThrow();

    // File must be untouched — overwriting would wipe whatever the user had.
    expect(await fs.promises.readFile(filePath, "utf-8")).toBe(original);
  });

  it("persists PostHog exec approvals and sees them across worktrees", async () => {
    const writer = new SettingsManager(worktree);
    await writer.initialize();
    await writer.addPostHogExecApproval("experiment-update");

    const filePath = path.join(mainRepo, ".claude", "settings.local.json");
    const contents = JSON.parse(await fs.promises.readFile(filePath, "utf-8"));
    expect(contents.posthogApprovedExecTools).toEqual(["experiment-update"]);

    const sibling = path.join(tmpRoot, "wt-ph");
    runGit(mainRepo, ["worktree", "add", "-b", "other-ph", sibling]);
    const reader = new SettingsManager(sibling);
    await reader.initialize();
    expect(reader.hasPostHogExecApproval("experiment-update")).toBe(true);
    expect(reader.hasPostHogExecApproval("experiment-delete")).toBe(false);
  });

  it("dedupes repeated PostHog exec approvals", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await manager.addPostHogExecApproval("foo-update");
    await manager.addPostHogExecApproval("foo-update");
    await manager.addPostHogExecApproval("bar-delete");

    const filePath = path.join(mainRepo, ".claude", "settings.local.json");
    const contents = JSON.parse(await fs.promises.readFile(filePath, "utf-8"));
    expect(contents.posthogApprovedExecTools).toEqual([
      "foo-update",
      "bar-delete",
    ]);
  });

  it("concurrent addPostHogExecApproval calls do not clobber each other", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await Promise.all([
      manager.addPostHogExecApproval("a-update"),
      manager.addPostHogExecApproval("b-delete"),
      manager.addPostHogExecApproval("c-destroy"),
    ]);

    const filePath = path.join(mainRepo, ".claude", "settings.local.json");
    const contents = JSON.parse(await fs.promises.readFile(filePath, "utf-8"));
    expect(contents.posthogApprovedExecTools).toEqual(
      expect.arrayContaining(["a-update", "b-delete", "c-destroy"]),
    );
  });

  it("concurrent addAllowRules calls do not clobber each other", async () => {
    const manager = new SettingsManager(worktree);
    await manager.initialize();

    await Promise.all([
      manager.addAllowRules([{ toolName: "A" }]),
      manager.addAllowRules([{ toolName: "B" }]),
      manager.addAllowRules([{ toolName: "C" }]),
    ]);

    const filePath = path.join(mainRepo, ".claude", "settings.local.json");
    const contents = JSON.parse(await fs.promises.readFile(filePath, "utf-8"));
    expect(contents.permissions.allow).toEqual(
      expect.arrayContaining(["A", "B", "C"]),
    );
  });
});

describe("resolveMainRepoPath", () => {
  it("returns cwd when the directory is not inside a git repository", async () => {
    const tmp = await fs.promises.realpath(
      await fs.promises.mkdtemp(path.join(os.tmpdir(), "repo-path-")),
    );
    try {
      expect(await resolveMainRepoPath(tmp)).toBe(tmp);
    } finally {
      await fs.promises.rm(tmp, { recursive: true, force: true });
    }
  });
});

describe("availableModels merge", () => {
  let tmpRoot: string;
  let cwd: string;
  let configDir: string;
  let originalConfigDir: string | undefined;

  beforeEach(async () => {
    tmpRoot = await fs.promises.realpath(
      await fs.promises.mkdtemp(path.join(os.tmpdir(), "available-models-")),
    );
    cwd = path.join(tmpRoot, "repo");
    configDir = path.join(tmpRoot, "user");
    await fs.promises.mkdir(cwd, { recursive: true });
    await fs.promises.mkdir(configDir, { recursive: true });
    runGit(cwd, ["init", "-b", "main"]);
    runGit(cwd, ["config", "user.email", "test@example.com"]);
    runGit(cwd, ["config", "user.name", "test"]);
    runGit(cwd, ["commit", "--allow-empty", "-m", "init"]);

    originalConfigDir = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = configDir;
  });

  afterEach(async () => {
    if (originalConfigDir === undefined) {
      delete process.env.CLAUDE_CONFIG_DIR;
    } else {
      process.env.CLAUDE_CONFIG_DIR = originalConfigDir;
    }
    await fs.promises.rm(tmpRoot, { recursive: true, force: true });
  });

  async function writeUserSettings(settings: object): Promise<void> {
    await fs.promises.writeFile(
      path.join(configDir, "settings.json"),
      JSON.stringify(settings),
    );
  }

  async function writeProjectSettings(settings: object): Promise<void> {
    const projectDir = path.join(cwd, ".claude");
    await fs.promises.mkdir(projectDir, { recursive: true });
    await fs.promises.writeFile(
      path.join(projectDir, "settings.json"),
      JSON.stringify(settings),
    );
  }

  it("merges and dedupes availableModels across user and project layers", async () => {
    await writeUserSettings({ availableModels: ["model-a", "model-b"] });
    await writeProjectSettings({ availableModels: ["model-b", "model-c"] });

    const manager = new SettingsManager(cwd);
    await manager.initialize();

    expect(manager.getSettings().availableModels).toEqual([
      "model-a",
      "model-b",
      "model-c",
    ]);
  });

  it("passes through a single layer unchanged", async () => {
    await writeProjectSettings({ availableModels: ["only-one"] });

    const manager = new SettingsManager(cwd);
    await manager.initialize();

    expect(manager.getSettings().availableModels).toEqual(["only-one"]);
  });

  it("leaves availableModels undefined when no layer defines it", async () => {
    const manager = new SettingsManager(cwd);
    await manager.initialize();

    expect(manager.getSettings().availableModels).toBeUndefined();
  });
});

describe("mergeAvailableModels", () => {
  it("merges and dedupes non-enterprise layers", () => {
    expect(
      mergeAvailableModels(
        ["model-a", "model-b"],
        ["model-b", "model-c"],
        "project",
      ),
    ).toEqual(["model-a", "model-b", "model-c"]);
  });

  it("lets enterprise settings replace lower-precedence allowlists", () => {
    expect(
      mergeAvailableModels(
        ["model-a", "model-b"],
        ["managed-a", "managed-a"],
        "enterprise",
      ),
    ).toEqual(["managed-a"]);
  });
});
