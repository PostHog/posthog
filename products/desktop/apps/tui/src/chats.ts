import { execFileSync } from "node:child_process";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";
import type { CloudHarness } from "./billing";
import { savedImage } from "./images";
import type { SentImage } from "./transcript";

export type SendMessage = (
  taskId: string,
  runId: string,
  content: string,
  artifactIds: string[],
) => Promise<void>;

const PLAN_RUN: Record<Exclude<CloudHarness, "pi">, object> = {
  claude: { adapter: "claude", claudeModelAccess: "own-subscription" },
  codex: { adapter: "codex", codexModelAccess: "own-subscription" },
};

const runOptions = (harness: CloudHarness): object =>
  harness === "pi" ? { piRuntime: true } : PLAN_RUN[harness];

const harnessOf = (task: Task): CloudHarness | null => {
  if (task.runtime === "pi") return "pi";
  const adapter = (task as { runtime_adapter?: string | null }).runtime_adapter;
  return task.runtime === "acp" && (adapter === "claude" || adapter === "codex")
    ? adapter
    : null;
};

// Uploads images for a cloud run, as the desktop app does: to the task for a run still to start, or to a live run.
export interface ImageUploads {
  toTask(taskId: string, filePaths: string[]): Promise<string[]>;
  toRun(taskId: string, runId: string, filePaths: string[]): Promise<string[]>;
}

// The uploader reads files, so each image goes up from the copy the TUI keeps of it.
const filesOf = (images: SentImage[]): string[] => images.map(savedImage);
const pendingArtifacts = (artifactIds: string[]) =>
  artifactIds.length > 0 ? { pendingUserArtifactIds: artifactIds } : {};

// The GitHub repository of a directory, by default the one the TUI was started in, as "owner/name".
export function currentRepository(cwd?: string): string | null {
  try {
    const remote = execFileSync("git", ["remote", "get-url", "origin"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return remote.match(/github\.com[:/](.+?)(\.git)?$/)?.[1] ?? null;
  } catch {
    return null;
  }
}

// How many repositories each GitHub connection returns per search.
const REPOSITORY_PAGE = 30;

type GithubConnection =
  | { github_integration: number }
  | { github_user_integration: string }
  | Record<string, never>;

// What the command endpoint answers when a message is sent into a run that has ended.
const RUN_ENDED =
  /Failed to queue user message|Task run workflow has ended|No active sandbox/;
// What resume_in_cloud answers for a run the server still counts as running.
const STILL_ACTIVE = /already active/i;
const FINISHED = ["completed", "failed", "cancelled"];

// Waits for a run brought back with resume_in_cloud to have its agent running again, after `since` (epoch ms).
export type AgentRestarted = (
  taskId: string,
  runId: string,
  since: number,
) => Promise<void>;

const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

// Every chat here is a pi task: a cloud chat starts a run and replies go into it or resume it, and a local chat only needs the task.
export class PiChats {
  constructor(
    private readonly api: PostHogAPIClient,
    private readonly sendMessage: SendMessage,
    private readonly repository: string | null,
    private readonly uploads: ImageUploads,
    private readonly agentRestarted?: AgentRestarted,
  ) {}

  // `repositories` are the ones the sandbox clones; by default, the repository of the folder the TUI started in.
  async start(
    prompt: string,
    images: SentImage[] = [],
    repositories: string[] = this.repository ? [this.repository] : [],
    harness: CloudHarness = "pi",
  ): Promise<Task> {
    const task = await this.api.createTask({
      description: prompt,
      repository: repositories[0],
      ...(harness === "pi"
        ? { runtime: "pi" }
        : { runtime: "acp", runtime_adapter: harness }),
      // One repository needs nothing more: the server finds the GitHub connection that reaches it. Several need the
      // list and that connection named; the client's type does not list `repositories` yet.
      ...(repositories.length > 1
        ? { repositories, ...(await this.connectionFor(repositories[0])) }
        : {}),
    } as Parameters<PostHogAPIClient["createTask"]>[0]);
    const run = await this.api.createTaskRun(task.id, {
      environment: "cloud",
      mode: "interactive",
      ...runOptions(harness),
    });
    const artifactIds =
      images.length > 0
        ? await this.uploads.toTask(task.id, filesOf(images))
        : [];
    const started = await this.api.startTaskRun(task.id, run.id, {
      pendingUserMessage: prompt,
      ...pendingArtifacts(artifactIds),
    });
    return started.latest_run ? started : { ...started, latest_run: run };
  }

  // The GitHub repositories the team's integrations and the user's own GitHub connections can clone, matching `query`.
  async searchRepositories(query: string): Promise<string[]> {
    const [team, user] = await this.loadIntegrations();
    const connections: GithubConnection[] = [
      ...team.map((integration) => ({ github_integration: integration.id })),
      ...user.map((integration) => ({
        github_user_integration: integration.id,
      })),
    ];
    const pages = await Promise.allSettled([
      ...team.map((integration) =>
        this.api.getGithubRepositoriesPage(
          integration.id,
          0,
          REPOSITORY_PAGE,
          query || undefined,
        ),
      ),
      ...user.map((integration) =>
        this.api.getGithubUserRepositoriesPage(
          integration.installation_id,
          0,
          REPOSITORY_PAGE,
          query || undefined,
        ),
      ),
    ]);
    const found = pages.flatMap((page, index) => {
      if (page.status !== "fulfilled") return [];
      for (const repository of page.value.repositories)
        if (!this.connections.has(repository))
          this.connections.set(repository, connections[index]);
      return page.value.repositories;
    });
    if (found.length === 0) {
      const failed = pages.find((page) => page.status === "rejected");
      if (failed) throw failed.reason;
    }
    return [...new Set(found)];
  }

  private integrations: Promise<
    [{ id: number }[], { id: string; installation_id: string }[]]
  > | null = null;

  private loadIntegrations(): Promise<
    [{ id: number }[], { id: string; installation_id: string }[]]
  > {
    this.integrations ??= Promise.all([
      this.api
        .getIntegrations()
        .then((all) =>
          (all as { id: number; kind: string }[]).filter(
            (integration) => integration.kind === "github",
          ),
        ),
      this.api.getGithubUserIntegrations(),
    ]).catch((error: unknown) => {
      this.integrations = null;
      throw error;
    });
    return this.integrations;
  }

  // The GitHub connection each searched repository came from, which a task with several repositories must name.
  private readonly connections = new Map<string, GithubConnection>();

  // A repository never searched for falls back to the team's first GitHub integration.
  private async connectionFor(repository: string): Promise<GithubConnection> {
    const known = this.connections.get(repository);
    if (known) return known;
    const [team] = await this.loadIntegrations();
    return team[0] ? { github_integration: team[0].id } : {};
  }

  // A local chat's task row: the server names it from the first message, and the chat runs on this machine with no run.
  createLocal(
    prompt: string,
    repository = this.repository,
    harness: "pi" | "claude" = "pi",
  ): Promise<Task> {
    return this.api.createTask({
      description: prompt,
      repository: repository ?? undefined,
      ...(harness === "pi"
        ? { runtime: "pi" }
        : { runtime: "acp", runtime_adapter: "claude" }),
    });
  }

  // Renames the chat's task; the server keeps the title, so every client sees it.
  rename(taskId: string, title: string): Promise<Task> {
    return this.api.updateTask(taskId, { title });
  }

  // A reply goes into the chat's run. A run that has ended or lost its sandbox comes back first, as the desktop
  // app brings it back: the same run, restored from its snapshot. `onReopen` says that wait has begun, and again
  // with the run once the server has queued it to come back.
  async reply(
    task: Task,
    prompt: string,
    images: SentImage[] = [],
    onReopen?: (resumed?: Task) => void,
  ): Promise<Task> {
    const harness = harnessOf(task);
    if (!harness) {
      throw new Error("This chat's agent cannot be continued here");
    }
    const run = task.latest_run;
    if (!run) return this.start(prompt, images);
    const send = async (): Promise<void> => {
      const artifactIds =
        images.length > 0
          ? await this.uploads.toRun(task.id, run.id, filesOf(images))
          : [];
      await this.sendMessage(task.id, run.id, prompt, artifactIds);
    };
    if (!FINISHED.includes(run.status)) {
      try {
        await send();
        return task;
      } catch (error) {
        // The cached status can lag a run that just ended, or its sandbox may have stopped; bring it back.
        if (!RUN_ENDED.test(messageOf(error))) throw error;
      }
    }
    if (this.agentRestarted) {
      onReopen?.();
      const since = Date.now();
      const resumed = await this.api
        .resumeRunInCloud(task.id, run.id)
        .catch((error: unknown) => {
          // The server may still count the run as running; a new run that continues it still works.
          if (STILL_ACTIVE.test(messageOf(error))) return null;
          throw error;
        });
      if (resumed) {
        const reopened = { ...task, latest_run: { ...run, ...resumed } };
        onReopen?.(reopened);
        await this.agentRestarted(task.id, run.id, since);
        await send();
        return reopened;
      }
    }
    // Without a way back for the run, the reply starts a new run that continues it.
    const artifactIds =
      images.length > 0
        ? await this.uploads.toTask(task.id, filesOf(images))
        : [];
    return this.api.runTaskInCloud(task.id, null, {
      ...runOptions(harness),
      resumeFromRunId: run.id,
      pendingUserMessage: prompt,
      ...pendingArtifacts(artifactIds),
    });
  }
}
