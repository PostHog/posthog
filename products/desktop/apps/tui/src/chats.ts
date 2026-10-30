import { execFileSync } from "node:child_process";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";
import { savedImage } from "./images";
import type { SentImage } from "./transcript";

export type SendMessage = (
  taskId: string,
  runId: string,
  content: string,
  artifactIds: string[],
) => Promise<void>;

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

// What the command endpoint answers when a message is sent into a run that has ended.
const RUN_ENDED =
  /Failed to queue user message|Task run workflow has ended|No active sandbox/;

// Every chat here is a pi task: a cloud chat starts a run and replies go into it or resume it, and a local chat only needs the task.
export class PiChats {
  constructor(
    private readonly api: PostHogAPIClient,
    private readonly sendMessage: SendMessage,
    private readonly repository: string | null,
    private readonly uploads: ImageUploads,
  ) {}

  async start(prompt: string, images: SentImage[] = []): Promise<Task> {
    const task = await this.api.createTask({
      description: prompt,
      repository: this.repository ?? undefined,
      runtime: "pi",
    });
    const run = await this.api.createTaskRun(task.id, {
      environment: "cloud",
      mode: "interactive",
      piRuntime: true,
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

  // A local chat's task row: the server names it from the first message, and the chat runs on this machine with no run.
  createLocal(prompt: string, repository = this.repository): Promise<Task> {
    return this.api.createTask({
      description: prompt,
      repository: repository ?? undefined,
      runtime: "pi",
    });
  }

  async reply(
    task: Task,
    prompt: string,
    images: SentImage[] = [],
  ): Promise<Task> {
    if (task.runtime !== "pi") {
      throw new Error("Only pi chats can be continued here");
    }
    const run = task.latest_run;
    if (!run) return this.start(prompt, images);
    const sandboxStopped =
      (run.state as Record<string, unknown> | undefined)?.sandbox_alive ===
      false;
    const live =
      (run.status === "queued" || run.status === "in_progress") &&
      !sandboxStopped;
    if (live) {
      try {
        const artifactIds =
          images.length > 0
            ? await this.uploads.toRun(task.id, run.id, filesOf(images))
            : [];
        await this.sendMessage(task.id, run.id, prompt, artifactIds);
        return task;
      } catch (error) {
        // The cached status can lag a run that just ended; resume it like a finished one.
        if (!RUN_ENDED.test(error instanceof Error ? error.message : ""))
          throw error;
      }
    }
    // A finished run's sandbox is gone, so the reply starts a new run that resumes it.
    const artifactIds =
      images.length > 0
        ? await this.uploads.toTask(task.id, filesOf(images))
        : [];
    return this.api.runTaskInCloud(task.id, null, {
      piRuntime: true,
      resumeFromRunId: run.id,
      pendingUserMessage: prompt,
      ...pendingArtifacts(artifactIds),
    });
  }
}
