import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";

export interface RecentWork {
  tasks: Task[];
  hasMore: boolean;
}

export class WorkList {
  private userId: Promise<number> | null = null;

  constructor(private readonly api: PostHogAPIClient) {}

  async listRecent(limit: number): Promise<RecentWork> {
    // A failed lookup is dropped so the next refresh tries again.
    this.userId ??= this.api.getCurrentUser().then(
      (user) => user.id,
      (error: unknown) => {
        this.userId = null;
        throw error;
      },
    );
    const { tasks, count } = await this.api.getTasksPage({
      limit,
      basic: true,
      ordering: "-last_activity_at",
      createdBy: await this.userId,
    });
    return { tasks, hasMore: count > tasks.length };
  }
}
