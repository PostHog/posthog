import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";

export interface RecentWork {
  tasks: Task[];
  hasMore: boolean;
}

const LIST_TIMEOUT_MS = 20_000;
const SEARCH_LIMIT = 50;

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

  search(query: string): Promise<Task[]> {
    return this.fetch(SEARCH_LIMIT, query).then(({ tasks }) => tasks);
  }

  get(taskId: string): Promise<Task> {
    return this.api.getTask(taskId);
  }

  private async fetch(limit: number, search?: string): Promise<RecentWork> {
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
      search,
    });
    return { tasks, hasMore: count > tasks.length };
  }
}

// A task this app just started or resumed wins until the list shows the same run, so a new run appears at once.
export function findTask(
  taskId: string | null,
  sources: {
    listed: Task[] | null;
    known: Map<string, Task>;
    fresh: Map<string, Task>;
  },
): Task | undefined {
  if (!taskId) return undefined;
  const listed = sources.listed?.find((task) => task.id === taskId);
  const recent = sources.fresh.get(taskId);
  if (recent && recent.latest_run?.id !== listed?.latest_run?.id) return recent;
  return listed ?? sources.known.get(taskId) ?? recent;
}
