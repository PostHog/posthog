import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { TaskThreadMessage } from "@posthog/shared/domain-types";
import { injectable } from "inversify";

export const TASK_THREAD_SERVICE = Symbol.for(
  "posthog.core.canvas.taskThreadService",
);

export interface PostMessageToAgentResult {
  message: TaskThreadMessage;
  sendError: unknown | null;
}

@injectable()
export class TaskThreadService {
  async postMessageToAgent(
    client: PostHogAPIClient,
    taskId: string,
    content: string,
  ): Promise<PostMessageToAgentResult> {
    const message = await client.createTaskThreadMessage(taskId, content);
    try {
      return {
        message: await client.sendTaskThreadMessageToAgent(taskId, message.id),
        sendError: null,
      };
    } catch (sendError) {
      return { message, sendError };
    }
  }
}
