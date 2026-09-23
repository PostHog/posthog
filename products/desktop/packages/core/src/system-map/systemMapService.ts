import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import { z } from "zod";
import { SYSTEM_MAP_PROMPT } from "./prompt";
import {
  type SystemMap,
  systemMapOutputSchema,
  systemMapSchema,
} from "./schemas";

export const SYSTEM_MAP_AGENT = Symbol.for("posthog.core.systemMap.agent");
export const SYSTEM_MAP_SERVICE = Symbol.for("posthog.core.systemMap.service");
export interface SystemMapAgent {
  start: {
    mutate(input: {
      taskId: string;
      taskRunId: string;
      repoPath: string;
      apiHost: string;
      projectId: number;
      adapter: "claude";
      permissionMode: string;
      settingSources: ("user" | "project" | "local")[];
      systemPromptOverride: string;
      disallowedTools: string[];
      jsonSchema: Record<string, unknown>;
    }): Promise<unknown>;
  };
  prompt: {
    mutate(input: {
      sessionId: string;
      prompt: { type: "text"; text: string }[];
    }): Promise<unknown>;
  };
  cancel: { mutate(input: { sessionId: string }): Promise<unknown> };
}

export interface SystemMapRequest {
  repoPath: string;
  apiHost: string;
  projectId: number;
  signal: AbortSignal;
}

export interface SystemMapResult {
  map: SystemMap;
  taskId: string;
  runId: string;
  analyzedAt: string;
}

function withAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const onAbort = (): void => reject(signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    promise
      .then(resolve, reject)
      .finally(() => signal.removeEventListener("abort", onAbort));
    if (signal.aborted) onAbort();
  });
}

function wait(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, 2000);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

@injectable()
export class SystemMapService {
  private readonly running = new Set<string>();

  constructor(
    @inject(SYSTEM_MAP_AGENT) private readonly agent: SystemMapAgent,
    @inject(ROOT_LOGGER) private readonly logger: RootLogger,
  ) {}

  async analyze(
    client: PostHogAPIClient,
    request: SystemMapRequest,
  ): Promise<SystemMapResult> {
    const key = JSON.stringify([
      request.apiHost,
      request.projectId,
      request.repoPath,
    ]);
    if (this.running.has(key))
      throw new Error(
        "This repository is already being analyzed. Wait for the current analysis.",
      );
    this.running.add(key);
    const failure = new AbortController();
    const timeout = setTimeout(
      () =>
        failure.abort(
          new Error(
            "Analysis took too long. Try again with a smaller repository.",
          ),
        ),
      10 * 60 * 1000,
    );
    const signal = AbortSignal.any([request.signal, failure.signal]);
    let runId: string | undefined;
    const cancel = (): void => {
      if (runId)
        void this.agent.cancel.mutate({ sessionId: runId }).catch(() => {
          this.logger.warn("Could not stop system map agent");
        });
    };
    signal.addEventListener("abort", cancel, { once: true });
    try {
      signal.throwIfAborted();
      const jsonSchema = z.toJSONSchema(systemMapOutputSchema, {
        unrepresentable: "any",
      });
      const task = await withAbort(
        client.createTask({
          title: "Analyze system map",
          description: SYSTEM_MAP_PROMPT,
          json_schema: jsonSchema,
        }),
        signal,
      );
      signal.throwIfAborted();
      const run = await withAbort(
        client.createTaskRun(task.id, {
          environment: "local",
          adapter: "claude",
          initialPermissionMode: "plan",
        }),
        signal,
      );
      runId = run.id;
      signal.throwIfAborted();
      const starting = this.agent.start.mutate({
        taskId: task.id,
        taskRunId: run.id,
        repoPath: request.repoPath,
        apiHost: request.apiHost,
        projectId: request.projectId,
        adapter: "claude",
        permissionMode: "plan",
        settingSources: [],
        systemPromptOverride: SYSTEM_MAP_PROMPT,
        disallowedTools: [
          "Bash",
          "Write",
          "Edit",
          "NotebookEdit",
          "Agent",
          "Task",
          "EnterPlanMode",
          "ExitPlanMode",
          "AskUserQuestion",
          "WebFetch",
          "WebSearch",
          "Skill",
          "ToolSearch",
          "mcp__*",
        ],
        jsonSchema,
      });
      void starting.then(
        () => {
          if (signal.aborted) cancel();
        },
        () => {},
      );
      await withAbort(starting, signal);
      signal.throwIfAborted();
      void this.agent.prompt
        .mutate({
          sessionId: run.id,
          prompt: [{ type: "text", text: SYSTEM_MAP_PROMPT }],
        })
        .catch((error: unknown) => {
          failure.abort(error);
        });
      for (;;) {
        signal.throwIfAborted();
        const latest = await withAbort(
          client.getTaskRun(task.id, run.id),
          signal,
        );
        signal.throwIfAborted();
        const result = systemMapSchema.safeParse(latest.output);
        if (result.success) {
          return {
            map: result.data,
            taskId: task.id,
            runId: run.id,
            analyzedAt: new Date().toISOString(),
          };
        }
        if (latest.status === "completed")
          throw new Error(
            "The agent returned an invalid map. Try the analysis again.",
          );
        if (["failed", "cancelled"].includes(latest.status)) {
          throw new Error(
            "Analysis ended without a map. Try the analysis again.",
          );
        }
        await wait(signal);
      }
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", cancel);
      cancel();
      this.running.delete(key);
    }
  }
}
