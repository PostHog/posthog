import { execFileSync } from "node:child_process";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { ExecutionMode, Task } from "@posthog/shared";
import type { CloudHarness } from "./billing";
import { savedImage } from "./images";
import type { SentImage } from "./transcript";

export type SendMessage = (
  taskId: string,
  runId: string,
  content: string,
  artifactIds: string[],
) => Promise<void>;

type ModelAccess = "posthog-gateway" | "own-subscription";

// The model and effort picked before the chat started, if any.
export interface McpRelay {
  // The names of this machine's servers to relay, read as each run starts.
  servers: () => string[];
  designate: (runId: string, servers: string[]) => void;
}

const relayedOptions = (servers: string[]): object =>
  servers.length > 0
    ? { relayedMcpServers: servers.map((name) => ({ name })) }
    : {};

export interface StartPick {
  model?: string;
  effort?: string;
  // The permission mode a Claude Code chat starts in.
  mode?: string;
}

// A continued run keeps the agent and the payer of the run before it; desktop records both on the run.
const continuation = (task: Task): CloudHarness | null => {
  if (task.runtime === "pi") return "pi";
  if (task.runtime !== "acp") return null;
  const run = task.latest_run;
  return run?.runtime_adapter ?? "claude";
};

const runOptions = (
  harness: CloudHarness,
  run?: Task["latest_run"],
): object => {
  if (harness === "pi") return { piRuntime: true };
  const state = run?.state as
    | (Partial<Record<`${CloudHarness}_model_access`, ModelAccess>> & {
        model?: string;
      })
    | undefined;
  const access = run ? state?.[`${harness}_model_access`] : "own-subscription";
  return {
    adapter: harness,
    ...(access === "own-subscription" && { [`${harness}ModelAccess`]: access }),
    // The server requires a model on a run with an adapter; a continued run stays on the one the chat was on.
    ...(state?.model && { model: state.model }),
  };
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

// Watches a run until its agent reports in after `since` (epoch ms): one brought back with resume_in_cloud, or a new one.
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
    // This machine's MCP servers a cloud run reaches through the TUI: named on the run for the sandbox, and told to
    // the engine, which only answers a run it designated. pi takes none, as the desktop app gives it none.
    private readonly relay?: McpRelay,
  ) {}

  private relayed(harness: CloudHarness): string[] {
    return harness === "pi" ? [] : (this.relay?.servers() ?? []);
  }

  private designate(runId: string, harness: CloudHarness): void {
    const servers = this.relayed(harness);
    if (servers.length > 0) this.relay?.designate(runId, servers);
  }

  // `repositories` are the ones the sandbox clones; by default, the repository of the folder the TUI started in.
  async start(
    prompt: string,
    images: SentImage[] = [],
    repositories: string[] = this.repository ? [this.repository] : [],
    harness: CloudHarness = "pi",
    pick: StartPick = {},
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
      ...(pick.model && {
        model: pick.model,
        ...(pick.effort && { reasoningLevel: pick.effort }),
      }),
      ...(harness !== "pi" &&
        pick.mode && {
          initialPermissionMode: pick.mode as ExecutionMode,
        }),
      ...relayedOptions(this.relayed(harness)),
    });
    this.designate(run.id, harness);
    // Uploaded to the run, not staged on the task: the server resolves a pending message's artifacts on the run.
    const artifactIds =
      images.length > 0
        ? await this.uploads.toRun(task.id, run.id, filesOf(images))
        : [];
    const started = await this.api.startTaskRun(task.id, run.id, {
      pendingUserMessage: prompt,
      ...pendingArtifacts(artifactIds),
    });
    // A Claude Code or Codex sandbox asks the client for its plan's token once it boots, and only a watched
    // run answers. The panes' watch follows the user, so this one stays on the run until its agent is up.
    if (harness !== "pi")
      this.agentRestarted?.(task.id, run.id, Date.now()).catch(() => {});
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
    // The run's sandbox stopped answering (its log says a delivery got a 502) while the server still counts the run
    // as live: a send would land in the same hole, so the run is brought back first.
    { sandboxGone = false }: { sandboxGone?: boolean } = {},
  ): Promise<Task> {
    const harness = continuation(task);
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
    if (!FINISHED.includes(run.status) && !sandboxGone) {
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
    const continued = await this.api.runTaskInCloud(task.id, null, {
      ...runOptions(harness, run),
      ...relayedOptions(this.relayed(harness)),
      resumeFromRunId: run.id,
      pendingUserMessage: prompt,
      ...pendingArtifacts(artifactIds),
    });
    if (continued.latest_run) {
      this.designate(continued.latest_run.id, harness);
      // The new sandbox asks for the plan's token the same way a first run's does.
      if (harness !== "pi")
        this.agentRestarted?.(
          task.id,
          continued.latest_run.id,
          Date.now(),
        ).catch(() => {});
    }
    return continued;
  }
}
