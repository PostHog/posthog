import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { vi } from "vitest";
import type { PostHogAPIClient } from "../../posthog-api";
import type { TaskRun } from "../../types";

const execFileAsync = promisify(execFile);

export interface TestRepo {
  path: string;
  cleanup: () => Promise<void>;
  git: (args: string[]) => Promise<string>;
  writeFile: (relativePath: string, content: string) => Promise<void>;
  readFile: (relativePath: string) => Promise<string>;
  deleteFile: (relativePath: string) => Promise<void>;
  exists: (relativePath: string) => boolean;
}

export async function createTestRepo(prefix = "test-repo"): Promise<TestRepo> {
  const repoPath = join(
    tmpdir(),
    `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  await mkdir(repoPath, { recursive: true });

  const git = async (args: string[]): Promise<string> => {
    const { stdout } = await execFileAsync("git", args, { cwd: repoPath });
    return stdout.trim();
  };

  await git(["init"]);
  await git(["config", "user.email", "test@test.com"]);
  await git(["config", "user.name", "Test"]);
  await git(["config", "commit.gpgsign", "false"]);

  await writeFile(join(repoPath, ".gitignore"), ".posthog/\n");
  await writeFile(join(repoPath, "README.md"), "# Test Repo");
  await git(["add", "."]);
  await git(["commit", "-m", "Initial commit"]);

  return {
    path: repoPath,
    cleanup: () => rm(repoPath, { recursive: true, force: true }),
    git,
    writeFile: async (relativePath: string, content: string) => {
      const fullPath = join(repoPath, relativePath);
      const dir = join(fullPath, "..");
      await mkdir(dir, { recursive: true });
      await writeFile(fullPath, content);
    },
    readFile: async (relativePath: string) => {
      return readFile(join(repoPath, relativePath), "utf-8");
    },
    deleteFile: async (relativePath: string) => {
      await rm(join(repoPath, relativePath), { force: true });
    },
    exists: (relativePath: string) => {
      return existsSync(join(repoPath, relativePath));
    },
  };
}

export function createMockApiClient(
  overrides: Partial<PostHogAPIClient> = {},
): PostHogAPIClient {
  return {
    uploadTaskArtifacts: vi
      .fn()
      .mockResolvedValue([{ storage_path: "gs://bucket/handoff/test.pack" }]),
    downloadArtifact: vi.fn(),
    getTaskRun: vi.fn(),
    fetchTaskRunLogs: vi.fn(),
    ...overrides,
  } as unknown as PostHogAPIClient;
}

export function createTaskRun(overrides: Partial<TaskRun> = {}): TaskRun {
  return {
    id: "run-1",
    task: "task-1",
    team: 1,
    branch: null,
    stage: null,
    environment: "local",
    status: "in_progress",
    log_url: "https://logs.example.com/run-1",
    error_message: null,
    output: null,
    state: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
    ...overrides,
  };
}
