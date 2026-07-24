import type { Adapter } from "@posthog/shared";

export const INBOX_BULK_ACTION_SERVICE = Symbol.for(
  "posthog.core.inbox.bulkActionService",
);
export const SIGNAL_SOURCE_SERVICE = Symbol.for(
  "posthog.core.inbox.signalSourceService",
);
export const SIGNAL_REPORT_TASK_SERVICE = Symbol.for(
  "posthog.core.inbox.signalReportTaskService",
);
export const REPORT_MODEL_RESOLVER = Symbol.for(
  "posthog.core.inbox.reportModelResolver",
);
export const DATA_SOURCE_SERVICE = Symbol.for(
  "posthog.core.inbox.dataSourceService",
);
export const LINEAR_OAUTH_FLOW = Symbol.for(
  "posthog.core.inbox.linearOAuthFlow",
);

export interface ReportModelResolver {
  /**
   * Resolve the model id to use for a cloud task. `preferredModel` (e.g. the
   * persisted last-used model) is honoured only if the gateway still offers it;
   * otherwise the adapter's server default is returned.
   */
  resolveDefaultModel(
    apiHost: string,
    adapter: Adapter,
    preferredModel?: string | null,
  ): Promise<string | undefined>;
}

export interface LinearOAuthFlow {
  startFlow(region: string, projectId: number): Promise<void>;
}
