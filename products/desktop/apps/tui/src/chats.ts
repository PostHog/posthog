import { execFileSync } from "node:child_process";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";

export type SendMessage = (
  taskId: string,
  runId: string,
  content: string,
) => Promise<void>;

// The GitHub repository of the directory the TUI was started in, as "owner/name".
export function currentRepository(): string | null {
  try {
    const remote = execFileSync("git", ["remote", "get-url", "origin"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return remote.match(/github\.com[:/](.+?)(\.git)?$/)?.[1] ?? null;
  } catch {
    return null;
  }
}

// Every chat here is a pi cloud run: new chats start one, replies go into it or resume it.
export class PiChats {
  constructor(
    private readonly api: PostHogAPIClient,
    private readonly sendMessage: SendMessage,
    private readonly repository: string | null,
  ) {}

  async start(prompt: string): Promise<Task> {
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
    const started = await this.api.startTaskRun(task.id, run.id, {
      pendingUserMessage: prompt,
    });
    return started.latest_run ? started : { ...started, latest_run: run };
  }

  async reply(task: Task, prompt: string): Promise<Task> {
    if (task.runtime !== "pi") {
      throw new Error("Only pi chats can be continued here");
    }
    const run = task.latest_run;
    if (!run) return this.start(prompt);
    const sandboxStopped =
      (run.state as Record<string, unknown> | undefined)?.sandbox_alive ===
      false;
    const live =
      (run.status === "queued" || run.status === "in_progress") &&
      !sandboxStopped;
    if (live) {
      await this.sendMessage(task.id, run.id, prompt);
      return task;
    }
    // A finished run's sandbox is gone, so the reply starts a new run that resumes it.
    return this.api.runTaskInCloud(task.id, null, {
      piRuntime: true,
      resumeFromRunId: run.id,
      pendingUserMessage: prompt,
    });
  }
}
