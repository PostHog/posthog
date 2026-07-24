import type { Evaluation } from "@posthog/api-client/posthog-client";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useEvaluations } from "@posthog/ui/features/inbox/hooks/useEvaluations";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

/**
 * Read-and-toggle hook for LLM-Analytics evaluations exposed in the Inbox
 * source configuration UI. Owns its optimistic-toggle state so a click reflects
 * instantly without waiting for the API roundtrip.
 */
export function useSignalEvaluations() {
  const client = useAuthenticatedClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const queryClient = useQueryClient();
  const { data: evaluations } = useEvaluations();

  /** Optimistic enabled-overrides keyed by evaluation id. */
  const [optimisticEvals, setOptimisticEvals] = useState<
    Record<string, boolean>
  >({});

  const displayEvaluations = useMemo<Evaluation[]>(() => {
    if (!evaluations) return [];
    if (Object.keys(optimisticEvals).length === 0) return evaluations;
    return evaluations.map((e) =>
      e.id in optimisticEvals ? { ...e, enabled: optimisticEvals[e.id] } : e,
    );
  }, [evaluations, optimisticEvals]);

  const evaluationsUrl = useMemo(() => {
    if (!cloudRegion) return "";
    return `${getCloudUrlFromRegion(cloudRegion)}/llm-analytics/evaluations`;
  }, [cloudRegion]);

  const handleToggleEvaluation = useCallback(
    async (evaluationId: string, enabled: boolean) => {
      if (!client || !projectId) return;

      setOptimisticEvals((prev) => ({ ...prev, [evaluationId]: enabled }));

      try {
        await client.updateEvaluation(projectId, evaluationId, { enabled });
        await queryClient.invalidateQueries({ queryKey: ["evaluations"] });
      } catch (error: unknown) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to toggle evaluation";
        toast.error(message);
      } finally {
        setOptimisticEvals((prev) => {
          const next = { ...prev };
          delete next[evaluationId];
          return next;
        });
      }
    },
    [client, projectId, queryClient],
  );

  return {
    evaluations: displayEvaluations,
    evaluationsUrl,
    handleToggleEvaluation,
  };
}
