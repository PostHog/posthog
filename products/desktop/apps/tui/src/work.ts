import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";

export interface RecentWork {
  tasks: Task[];
  hasMore: boolean;
}

const LIST_TIMEOUT_MS = 20_000;

export class WorkList {
  private userId: Promise<number> | null = null;
  // Refreshes run on a timer, so a slow server would otherwise pile requests up behind each other.
  private inFlight: { limit: number; request: Promise<RecentWork> } | null =
    null;

  constructor(
    private readonly api: PostHogAPIClient,
    private readonly timeoutMs: number = LIST_TIMEOUT_MS,
  ) {}

  listRecent(limit: number): Promise<RecentWork> {
    if (this.inFlight?.limit === limit) return this.inFlight.request;
    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error("Timed out loading work")),
        this.timeoutMs,
      );
    });
    const request = Promise.race([this.fetch(limit), timeout]).finally(() => {
      clearTimeout(timer);
      if (this.inFlight?.request === request) this.inFlight = null;
    });
    this.inFlight = { limit, request };
    return request;
  }

  get(taskId: string): Promise<Task> {
    return this.api.getTask(taskId);
  }

  private async fetch(limit: number): Promise<RecentWork> {
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
