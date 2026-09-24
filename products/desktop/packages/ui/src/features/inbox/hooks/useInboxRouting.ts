import type { Schemas } from "@posthog/api-client/generated";
import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { loadRoutingCatalogue } from "@posthog/core/inbox/routing";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useQueryClient } from "@tanstack/react-query";

const routingKeys = {
  all: ["inbox-routing"] as const,
  catalogue: ["inbox-routing", "catalogue"] as const,
};
export function useRoutingCatalogue(enabled = true) {
  return useAuthenticatedQuery(routingKeys.catalogue, loadRoutingCatalogue, {
    enabled,
  });
}
export function useReportRouting(reportId: string) {
  return useAuthenticatedQuery(
    [...routingKeys.all, "report", reportId],
    (client) => client.getReportRouting(reportId),
  );
}
export function useRoutingBatch(batchId: string | null) {
  return useAuthenticatedQuery(
    [...routingKeys.all, "batch", batchId],
    (client) => {
      if (!batchId) throw new Error("Choose a routing operation");
      return client.getRoutingBatch(batchId);
    },
    {
      enabled: batchId !== null,
      refetchInterval: (query) =>
        ["pending", "running", "undoing"].includes(
          query.state.data?.status ?? "",
        )
          ? 2500
          : false,
    },
  );
}
export function useRoutingBatchReports(batchId: string | null, offset: number) {
  return useAuthenticatedQuery(
    [...routingKeys.all, "batch-reports", batchId, offset],
    (client) => {
      if (!batchId) throw new Error("Choose a routing operation");
      return client.getRoutingBatchReports(batchId, offset);
    },
    { enabled: batchId !== null },
  );
}

type RoutingAction =
  | { type: "preview"; domainId: string }
  | { type: "allow"; domainId: string }
  | { type: "apply" | "undo" | "retry"; batchId: string }
  | { type: "not-me" | "restore"; reportId: string }
  | {
      type: "correct";
      reportId: string;
      correction: Schemas.SignalRoutingCorrection;
    };

export function useRoutingAction() {
  const cache = useQueryClient();
  return useAuthenticatedMutation(
    async (client, action: RoutingAction) => {
      switch (action.type) {
        case "preview":
          return client.previewRoutingDomain({ domain_id: action.domainId });
        case "allow":
          return client.setRoutingPreference({
            domain_id: action.domainId,
            excluded: false,
          });
        case "apply":
          return client.applyRoutingBatch(action.batchId);
        case "undo":
          return client.undoRoutingBatch(action.batchId);
        case "retry":
          return client.retryRoutingBatch(action.batchId);
        case "not-me":
          return client.removeRoutingSuggestion(action.reportId);
        case "restore":
          return client.restoreRoutingSuggestion(action.reportId);
        case "correct":
          return client.correctReportRouting(
            action.reportId,
            action.correction,
          );
      }
    },
    {
      onSuccess: async () => {
        await Promise.all([
          cache.invalidateQueries({ queryKey: routingKeys.all }),
          cache.invalidateQueries({ queryKey: inboxReportKeys.all }),
        ]);
      },
    },
  );
}
