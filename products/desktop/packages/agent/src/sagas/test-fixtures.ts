import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type { SagaLogger } from "@posthog/shared";
import { vi } from "vitest";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import type { PostHogAPIClient } from "../posthog-api";
import type { GitCheckpointEvent, StoredNotification, TaskRun } from "../types";

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

export async function cloneTestRepo(
  sourcePath: string,
  prefix = "test-repo-clone",
): Promise<TestRepo> {
  const clonePath = join(
    tmpdir(),
    `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  await execFileAsync("git", ["clone", sourcePath, clonePath]);
  await execFileAsync("git", ["config", "user.email", "test@test.com"], {
    cwd: clonePath,
  });
  await execFileAsync("git", ["config", "user.name", "Test"], {
    cwd: clonePath,
  });
  await execFileAsync("git", ["config", "commit.gpgsign", "false"], {
    cwd: clonePath,
  });

  const git = async (args: string[]): Promise<string> => {
    const { stdout } = await execFileAsync("git", args, { cwd: clonePath });
    return stdout.trim();
  };

  return {
    path: clonePath,
    cleanup: () => rm(clonePath, { recursive: true, force: true }),
    git,
    writeFile: async (relativePath: string, content: string) => {
      const fullPath = join(clonePath, relativePath);
      const dir = join(fullPath, "..");
      await mkdir(dir, { recursive: true });
      await writeFile(fullPath, content);
    },
    readFile: async (relativePath: string) => {
      return readFile(join(clonePath, relativePath), "utf-8");
    },
    deleteFile: async (relativePath: string) => {
      await rm(join(clonePath, relativePath), { force: true });
    },
    exists: (relativePath: string) => {
      return existsSync(join(clonePath, relativePath));
    },
  };
}

export function createMockLogger(): SagaLogger {
  return {
    info: vi.fn(),
    debug: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
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

export function createNotification(
  method: string,
  params: Record<string, unknown>,
): StoredNotification {
  return {
    type: "notification",
    timestamp: new Date().toISOString(),
    notification: {
      jsonrpc: "2.0",
      method,
      params,
    },
  };
}

export function createUserMessage(content: string): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "user_message",
      content: { type: "text", text: content },
    },
  });
}

export function createAgentChunk(text: string): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
  });
}

export function createAgentMessage(text: string): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "agent_message",
      content: { type: "text", text },
    },
  });
}

export function createToolCall(
  toolCallId: string,
  toolName: string,
  toolInput: unknown,
): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "tool_call",
      _meta: {
        claudeCode: { toolCallId, toolName, toolInput },
      },
    },
  });
}

export function createToolResult(
  toolCallId: string,
  toolResponse: unknown,
): StoredNotification {
  return createNotification("session/update", {
    update: {
      sessionUpdate: "tool_result",
      _meta: {
        claudeCode: { toolCallId, toolResponse },
      },
    },
  });
}

export function createGitCheckpointNotification(
  overrides: Partial<GitCheckpointEvent> = {},
): StoredNotification {
  return createNotification(POSTHOG_NOTIFICATIONS.GIT_CHECKPOINT, {
    checkpointId: "checkpoint-1",
    commit: "commit-1",
    checkpointRef: "refs/posthog-code-checkpoint/checkpoint-1",
    headRef: "refs/posthog-code-handoff/head/checkpoint-1",
    head: "head-1",
    branch: "main",
    indexTree: "index-tree-1",
    worktreeTree: "worktree-tree-1",
    timestamp: new Date().toISOString(),
    upstreamRemote: "origin",
    upstreamMergeRef: "refs/heads/main",
    remoteUrl: "git@github.com:posthog/posthog.git",
    ...overrides,
  });
}
