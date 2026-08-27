import { type PostHogAPIClient, transferTimeoutMs } from "../../../posthog-api";
import type {
  ArtifactSource,
  ArtifactType,
  TaskRunArtifact,
} from "../../../types";

export const MAX_ARTIFACT_UPLOAD_BYTES = 30 * 1024 * 1024;
// The inline fallback base64-encodes the file into a JSON body, so it is held to a lower
// ceiling than a direct-to-storage POST to stay under the API's request size limit.
export const MAX_INLINE_UPLOAD_BYTES = 10 * 1024 * 1024;

export interface ArtifactUpload {
  name: string;
  contentType: string;
  content: Buffer;
  /**
   * Manifest classification. Only user-facing deliverables are "output" — every
   * deliverable surface filters on exactly that type — so other consumers (e.g.
   * peer-message attachments) must classify themselves as something else.
   */
  type: ArtifactType;
  source: ArtifactSource;
}

/**
 * Upload a file to the run's artifact manifest, preferring the direct-to-storage
 * path and falling back to the inline API upload when storage is unreachable
 * (a split network, or an egress allowlist that omits the bucket). Returns the
 * finalized manifest entry.
 */
export async function uploadRunArtifact(
  client: PostHogAPIClient,
  taskId: string,
  taskRunId: string,
  upload: ArtifactUpload,
): Promise<TaskRunArtifact> {
  try {
    return await uploadDirect(client, taskId, taskRunId, upload);
  } catch (error) {
    if (upload.content.byteLength > MAX_INLINE_UPLOAD_BYTES) {
      throw error;
    }
    return await uploadInline(client, taskId, taskRunId, upload);
  }
}

/** Reserve a storage key, POST the bytes straight to object storage, then attach them. */
async function uploadDirect(
  client: PostHogAPIClient,
  taskId: string,
  taskRunId: string,
  { name, contentType, content, type, source }: ArtifactUpload,
): Promise<TaskRunArtifact> {
  const [prepared] = await client.prepareTaskArtifactUploads(
    taskId,
    taskRunId,
    [
      {
        name,
        type,
        source,
        size: content.byteLength,
        content_type: contentType,
      },
    ],
  );
  if (!prepared) {
    throw new Error("PostHog did not prepare the artifact upload.");
  }

  const form = new FormData();
  for (const [key, value] of Object.entries(prepared.presigned_post.fields)) {
    form.append(key, value);
  }
  form.append(
    "file",
    new Blob([new Uint8Array(content)], { type: contentType }),
    name,
  );
  const response = await fetch(prepared.presigned_post.url, {
    method: "POST",
    body: form,
    // Scaled to the payload: a slow-but-working link gets time to finish a large
    // upload, while a stall still aborts long before undici's internal defaults.
    // The prepare/finalize legs carry the flat control-plane deadline inside the
    // client methods.
    signal: AbortSignal.timeout(transferTimeoutMs(content.byteLength)),
  });
  if (!response.ok) {
    throw new Error(`Artifact storage upload failed (${response.status}).`);
  }

  const finalized = await client.finalizeTaskArtifactUploads(
    taskId,
    taskRunId,
    [
      {
        id: prepared.id,
        name,
        type,
        source,
        storage_path: prepared.storage_path,
        content_type: contentType,
      },
    ],
  );
  const entry = finalized.find(
    (artifact) => artifact.storage_path === prepared.storage_path,
  );
  if (!entry) {
    throw new Error("PostHog did not confirm the artifact upload.");
  }
  return entry;
}

/** Send the bytes through the PostHog API and let the backend write them to storage. */
async function uploadInline(
  client: PostHogAPIClient,
  taskId: string,
  taskRunId: string,
  { name, contentType, content, type, source }: ArtifactUpload,
): Promise<TaskRunArtifact> {
  const manifest = await client.uploadTaskArtifacts(taskId, taskRunId, [
    {
      name,
      type,
      source,
      content: content.toString("base64"),
      content_encoding: "base64",
      content_type: contentType,
    },
  ]);
  // The client returns the entries for this upload request only, newest last.
  const entry = manifest.at(-1);
  if (!entry) {
    throw new Error("PostHog did not confirm the artifact upload.");
  }
  return entry;
}
