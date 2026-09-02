import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback, useState } from "react";

export interface ArtifactDownloadRef {
  taskId: string;
  runId: string;
  artifactId: string;
  name: string;
}

export interface ArtifactDownload {
  download: (ref: ArtifactDownloadRef) => Promise<void>;
  /** Artifact id currently being fetched. Shared lists must disable every download until it clears. */
  downloadingId: string | null;
}

/**
 * Save a task-run artifact to disk. The link an artifact was rendered from is
 * presigned and short-lived, so every download mints a fresh URL through the
 * API instead of reusing it.
 */
export function useArtifactDownload(): ArtifactDownload {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const download = useCallback(
    async (ref: ArtifactDownloadRef) => {
      if (downloadingId !== null) return;
      setDownloadingId(ref.artifactId);
      try {
        const url = await sessionService.getCloudAttachmentPreviewUrl(
          ref.taskId,
          ref.runId,
          ref.artifactId,
        );
        if (!url) {
          toast.error("This file is no longer available");
          return;
        }
        const response = await fetch(url);
        if (!response.ok) throw new Error("Artifact download failed");
        const objectUrl = URL.createObjectURL(await response.blob());
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = ref.name;
        anchor.click();
        URL.revokeObjectURL(objectUrl);
      } catch {
        toast.error("Couldn't download file");
      } finally {
        setDownloadingId(null);
      }
    },
    [downloadingId, sessionService],
  );

  return { download, downloadingId };
}
