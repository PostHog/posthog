import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as FileSystem from "expo-file-system/legacy";
import { getProjectId } from "@/lib/api";
import { logger } from "@/lib/logger";
import { uploadTaskRunArtifact } from "../api";
import type { PendingAttachment } from "../composer/attachments/types";
import {
  buildArtifactUploadRequest,
  uploadSizeError,
} from "../utils/artifactUpload";

const log = logger.scope("artifactUpload");

/**
 * Pickers only sometimes report a size (`ImagePicker` omits it for some
 * sources), and the prepare step needs an exact byte count, so stat the file
 * when we have to.
 */
async function resolveSizeBytes(
  attachment: PendingAttachment,
): Promise<number> {
  if (attachment.sizeBytes !== undefined) return attachment.sizeBytes;
  const info = await FileSystem.getInfoAsync(attachment.uri);
  if (!info.exists) {
    throw new Error(`${attachment.fileName} could not be read.`);
  }
  return info.size;
}

/**
 * Uploads a picked file into a terminal run's artifact manifest and refreshes
 * the artifact list. The mutation keeps the failed attachment in `variables`
 * so the caller can offer a retry without re-opening the picker.
 */
export function useUploadTaskRunArtifact(
  taskId: string | undefined,
  runId: string | undefined,
) {
  const queryClient = useQueryClient();
  const projectId = getProjectId();

  return useMutation({
    // The mutationFn is the whole prepare -> S3 -> finalize flow; a blanket
    // retry re-uploads up to 30MB for failures that can never succeed twice.
    retry: false,
    mutationFn: async (attachment: PendingAttachment): Promise<void> => {
      if (!taskId || !runId) {
        throw new Error("This run can't accept files.");
      }

      const sizeBytes = await resolveSizeBytes(attachment);
      const upload = buildArtifactUploadRequest(attachment, sizeBytes);
      const sizeError = uploadSizeError(
        upload.name,
        upload.content_type ?? "",
        sizeBytes,
      );
      if (sizeError) throw new Error(sizeError);

      await uploadTaskRunArtifact(taskId, runId, {
        uri: attachment.uri,
        upload,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["taskRunArtifacts", projectId, taskId, runId],
      });
    },
    onError: (error) => {
      log.error("Artifact upload failed", error);
    },
  });
}
