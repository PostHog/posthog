import type { Schemas } from "@posthog/api-client";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { SignalReport, Task } from "@posthog/shared/types";
import { injectable } from "inversify";
import {
  deriveReportImplementationState,
  type ReportImplementationState,
  reportImplementationTaskId,
} from "./reportImplementation";

export const REPORT_IMPLEMENTATION_SERVICE = Symbol.for(
  "posthog.core.inbox.reportImplementationService",
);

@injectable()
export class ReportImplementationService {
  private readonly completedTasks = new WeakMap<
    PostHogAPIClient,
    Map<string, { version: string; expiresAt: number; task: Promise<Task> }>
  >();

  initialStates(
    reports: SignalReport[],
    lookupFailed = false,
  ): Map<string, ReportImplementationState | null> {
    return new Map(
      reports.map((report) => [
        report.id,
        deriveReportImplementationState(report, undefined, lookupFailed),
      ]),
    );
  }

  /**
   * The states to show while a fetch is in flight. A report that gains or
   * finishes a task changes the query key, so the next fetch starts with
   * nothing. `known` carries what the last fetch resolved, so only a report
   * that was never checked falls back to "checking".
   */
  pendingStates(
    reports: SignalReport[],
    known: ReadonlyMap<string, ReportImplementationState | null>,
    lookupFailed = false,
  ): Map<string, ReportImplementationState | null> {
    const states = this.initialStates(reports, lookupFailed);
    for (const [id, state] of states) {
      if (state !== "checking") continue;
      const previous = known.get(id);
      if (previous !== undefined) states.set(id, previous);
    }
    return states;
  }

  private async completedTask(
    client: PostHogAPIClient,
    summary: Schemas.TaskSummaryDTO,
  ): Promise<Task> {
    let cache = this.completedTasks.get(client);
    if (!cache) {
      cache = new Map();
      this.completedTasks.set(client, cache);
    }
    const version = `${summary.updated_at}:${summary.latest_run?.id}`;
    const cached = cache.get(summary.id);
    if (cached?.version === version && cached.expiresAt > Date.now())
      return cached.task;
    const task = client.getTask(summary.id);
    cache.set(summary.id, {
      version,
      expiresAt: Date.now() + 5 * 60_000,
      task,
    });
    if (cache.size > 400) {
      const oldest = cache.keys().next().value;
      if (oldest) cache.delete(oldest);
    }
    try {
      return await task;
    } catch (error) {
      cache.delete(summary.id);
      throw error;
    }
  }

  async loadStates(
    client: PostHogAPIClient,
    reports: SignalReport[],
  ): Promise<Map<string, ReportImplementationState | null>> {
    const ids = [
      ...new Set(
        reports
          .map(reportImplementationTaskId)
          .filter((id): id is string => id !== null),
      ),
    ];
    if (!ids.length) return this.initialStates(reports);
    const summaries = await client.getTaskSummaries(ids);
    const tasks = new Map<
      string,
      Parameters<typeof deriveReportImplementationState>[1]
    >(summaries.map((summary) => [summary.id, summary]));
    const completed = summaries.filter(
      (summary) => summary.latest_run?.status === "completed",
    );
    for (let offset = 0; offset < completed.length; offset += 10) {
      await Promise.all(
        completed.slice(offset, offset + 10).map(async (summary) => {
          try {
            tasks.set(summary.id, await this.completedTask(client, summary));
          } catch {
            tasks.delete(summary.id);
          }
        }),
      );
    }
    return new Map(
      reports.map((report) => {
        const taskId = reportImplementationTaskId(report);
        const task = taskId ? tasks.get(taskId) : undefined;
        return [
          report.id,
          deriveReportImplementationState(report, task, !!taskId && !task),
        ];
      }),
    );
  }
}
