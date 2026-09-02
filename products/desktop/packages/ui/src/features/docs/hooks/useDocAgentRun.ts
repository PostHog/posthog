import { TASK_SERVICE } from "@posthog/core/task-detail/identifiers";
import type { TaskService } from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { useCallback } from "react";
import {
  DOC_AGENT_ADAPTER,
  DOC_AGENT_EXECUTION_MODE,
  DOC_AGENT_MODEL,
  DOC_AGENT_REASONING_EFFORT,
  DOC_AGENT_RUNTIME,
  DOC_AGENT_WORKSPACE_MODE,
  docTaskTitle,
} from "./docAgent";

/**
 * Starts the page's agent on one question.
 *
 * The task goes through the same path the composer uses, so a local run gets
 * its scratch directory and its harness the way every other run does. The page
 * never picks a repository, a model, or a mode.
 */
export function useDocAgentRun(options: { channelId: string }) {
  const taskService = useService<TaskService>(TASK_SERVICE);

  return useCallback(
    async (input: {
      question: string;
      description: string;
      titleFallback: string;
      outputSchema?: Record<string, unknown>;
    }): Promise<Task> => {
      const result = await taskService.createTask({
        content: input.question,
        taskDescription: input.description,
        channelId: options.channelId,
        workspaceMode: DOC_AGENT_WORKSPACE_MODE,
        runtime: DOC_AGENT_RUNTIME,
        adapter: DOC_AGENT_ADAPTER,
        model: DOC_AGENT_MODEL,
        reasoningLevel: DOC_AGENT_REASONING_EFFORT,
        executionMode: DOC_AGENT_EXECUTION_MODE,
        outputSchema: input.outputSchema,
        allowNoRepo: true,
      });

      if (!result.success) throw new Error(result.error);
      return result.data.task;
    },
    [options.channelId, taskService],
  );
}

export { docTaskTitle };
