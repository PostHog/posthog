import { ensureFlowHandoffArtifact } from "@posthog/core/sessions/flowHandoffArtifacts";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { type AgentFlowHandoff, agentFlowHandoffSchema } from "@posthog/shared";
import { useQuery, useQueryClient } from "@tanstack/react-query";

export function readFlowHandoff(value: unknown): AgentFlowHandoff | null {
  const parsed = agentFlowHandoffSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/**
 * Stores the handoff document as a task artifact, once per version. The key
 * holds the result, so the step card and its review card share one upload.
 */
export function useFlowHandoffArtifact(
  taskId: string | null,
  handoff: AgentFlowHandoff | null,
) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: [
      "flow-handoff-artifact",
      taskId,
      handoff?.artifactName,
      handoff?.version,
    ],
    queryFn: async () => {
      const document = handoff as AgentFlowHandoff;
      const stored = await ensureFlowHandoffArtifact(sessionService, {
        taskId: taskId as string,
        name: document.artifactName,
        version: document.version,
        markdown: document.markdown,
      });
      // The run manifest is server state that nothing pushes. Without this the
      // viewer keeps the older version, and the comments pane misses the target.
      await queryClient.invalidateQueries({ queryKey: ["task-runs", taskId] });
      return stored;
    },
    enabled: !!taskId && !!handoff,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}
