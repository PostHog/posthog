import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getProjectId } from "@/lib/api";
import { getTaskRun, presignTaskRunArtifact } from "../api";
import type { CloudArtifactRef } from "../types";

// Presigned URLs outlive this comfortably (backend issues ~1h), so we refetch
// well before expiry rather than on every render.
const PREVIEW_STALE_MS = 50 * 60 * 1000;

/**
 * Resolves a cloud attachment to a presigned S3 preview URL. The run's artifact
 * manifest is fetched once per run through the shared query cache, so a message
 * with several images does not fire a manifest request per image. Returns
 * `null` when the artifact is missing so callers can fall back to a file chip.
 */
export function useCloudAttachmentPreview(
  taskId: string | undefined,
  cloudArtifact: CloudArtifactRef | undefined,
) {
  const queryClient = useQueryClient();
  const projectId = getProjectId();

  return useQuery({
    queryKey: [
      "cloudArtifactPreview",
      projectId,
      taskId,
      cloudArtifact?.runId,
      cloudArtifact?.artifactId,
    ],
    enabled: Boolean(taskId && cloudArtifact),
    staleTime: PREVIEW_STALE_MS,
    retry: false,
    queryFn: async () => {
      if (!taskId || !cloudArtifact) return null;
      const { runId, artifactId } = cloudArtifact;
      const artifacts = await queryClient.fetchQuery({
        queryKey: ["taskRunArtifacts", projectId, taskId, runId],
        queryFn: async () => (await getTaskRun(taskId, runId)).artifacts ?? [],
        staleTime: PREVIEW_STALE_MS,
      });
      const match = artifacts.find((artifact) => artifact.id === artifactId);
      if (!match?.storage_path) return null;
      return presignTaskRunArtifact(taskId, runId, match.storage_path);
    },
  });
}
