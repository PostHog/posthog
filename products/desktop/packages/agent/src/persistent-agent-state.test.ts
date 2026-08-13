import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readlink,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configurePersistentAgentState } from "./persistent-agent-state";

describe("configurePersistentAgentState", () => {
  let testRoot: string;
  let homeDir: string;
  let stateRoot: string;

  beforeEach(async () => {
    testRoot = await mkdtemp(path.join(tmpdir(), "persistent-agent-state-"));
    homeDir = path.join(testRoot, "home");
    stateRoot = path.join(testRoot, "workspace", ".posthog", "agent-state");
    vi.stubEnv("CLAUDE_CONFIG_DIR", "");
    vi.stubEnv("CODEX_HOME", "");
  });

  afterEach(async () => {
    vi.unstubAllEnvs();
    await rm(testRoot, { recursive: true, force: true });
  });

  it("routes native session state into the durable workspace root", async () => {
    const claudeSkillsDir = path.join(homeDir, ".claude", "skills");
    const claudeProjectsDir = path.join(homeDir, ".claude", "projects");
    const claudeSessionEnvDir = path.join(homeDir, ".claude", "session-env");
    const codexSessionsDir = path.join(homeDir, ".codex", "sessions");
    const codexConfigPath = path.join(homeDir, ".codex", "config.toml");
    const restoredSessionEnvDir = path.join(stateRoot, "claude", "session-env");
    await mkdir(claudeSkillsDir, { recursive: true });
    await mkdir(claudeProjectsDir, { recursive: true });
    await mkdir(claudeSessionEnvDir, { recursive: true });
    await mkdir(codexSessionsDir, { recursive: true });
    await mkdir(path.dirname(codexConfigPath), { recursive: true });
    await mkdir(restoredSessionEnvDir, { recursive: true });
    await writeFile(path.join(claudeSkillsDir, "catalog.txt"), "fresh");
    await writeFile(path.join(claudeProjectsDir, "session.jsonl"), "claude");
    await writeFile(path.join(restoredSessionEnvDir, "restored"), "state");
    await writeFile(path.join(codexSessionsDir, "rollout.jsonl"), "codex");
    await writeFile(codexConfigPath, "fresh = true");

    await configurePersistentAgentState(stateRoot, homeDir);

    const mappings = [
      [".claude/projects", "claude/projects"],
      [".claude/session-env", "claude/session-env"],
      [".claude/plans", "claude/plans"],
      [".claude/todos", "claude/todos"],
      [".codex/sessions", "codex/sessions"],
      [".codex/shell_snapshots", "codex/shell_snapshots"],
    ];

    for (const [sourceRelative, targetRelative] of mappings) {
      const source = path.join(homeDir, sourceRelative);
      const target = path.join(stateRoot, targetRelative);
      expect((await lstat(source)).isSymbolicLink()).toBe(true);
      expect(path.resolve(path.dirname(source), await readlink(source))).toBe(
        target,
      );
      await writeFile(path.join(source, "marker"), sourceRelative);
      await expect(
        readFile(path.join(target, "marker"), "utf-8"),
      ).resolves.toBe(sourceRelative);
    }

    await configurePersistentAgentState(stateRoot, homeDir);

    await expect(
      readFile(
        path.join(stateRoot, "claude", "projects", "session.jsonl"),
        "utf-8",
      ),
    ).resolves.toBe("claude");
    await expect(
      readFile(
        path.join(stateRoot, "codex", "sessions", "rollout.jsonl"),
        "utf-8",
      ),
    ).resolves.toBe("codex");
    await expect(
      readFile(path.join(restoredSessionEnvDir, "restored"), "utf-8"),
    ).resolves.toBe("state");

    await expect(
      readFile(path.join(claudeSkillsDir, "catalog.txt"), "utf-8"),
    ).resolves.toBe("fresh");
    await expect(readFile(codexConfigPath, "utf-8")).resolves.toBe(
      "fresh = true",
    );
  });
});
