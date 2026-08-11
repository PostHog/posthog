import { inject, injectable } from "inversify";
import type { ChannelTaskRecord } from "./channelTaskSchemas";
import { PROJECT_API_CLIENT, type ProjectApiClient } from "./projectApiClient";

interface ApiTask {
  id: string;
  channel: string | null;
  created_at: string;
}

/**
 * Files tasks into channels. A filing is simply the task's `channel` field on
 * the PostHog tasks API — one channel per task, no side-table.
 */
@injectable()
export class ChannelTasksService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async list(channelId: string): Promise<ChannelTaskRecord[]> {
    const rows = await this.api.listPaginated<ApiTask>(
      `tasks/?channel=${encodeURIComponent(channelId)}`,
      "list channel tasks",
      { limit: 200 },
    );
    return rows.map((task) => ({
      channelId,
      taskId: task.id,
      createdAt: Date.parse(task.created_at) || 0,
    }));
  }

  async file(input: {
    channelId: string;
    taskId: string;
  }): Promise<ChannelTaskRecord> {
    const task = await this.setChannel(input.taskId, input.channelId);
    return {
      channelId: input.channelId,
      taskId: task.id,
      createdAt: Date.parse(task.created_at) || 0,
    };
  }

  // Unfile a task from its channel (clears the task's channel field).
  async unfile(taskId: string): Promise<void> {
    await this.setChannel(taskId, null);
  }

  private setChannel(
    taskId: string,
    channelId: string | null,
  ): Promise<ApiTask> {
    return this.api.json<ApiTask>(
      `tasks/${encodeURIComponent(taskId)}/`,
      "file task to channel",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: channelId }),
      },
    );
  }
}
