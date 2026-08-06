import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export function useSaveArtifactVersion(taskId: string, artifactId: string) {
  const service = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      runId: string;
      expectedVersionId: string;
      name: string;
      contentType: string;
      content: string;
    }) =>
      service.saveCloudArtifactVersion({
        ...input,
        taskId,
        artifactId,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["artifactVersions"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["task-runs", taskId],
        }),
      ]);
    },
  });
}
