import type {
  PreparedTaskArtifactUpload,
  TaskArtifactUploadRequest,
} from "@posthog/api-client/posthog-client";
import * as ImagePicker from "expo-image-picker";
import { getClient } from "@/lib/client";

export const MAX_PHOTOS = 10;
const MAX_PHOTO_BYTES = 30 * 1024 * 1024;

export interface Photo {
  id: string;
  uri: string;
  name: string;
  mimeType: string;
  size: number;
}

export async function pickPhotos(remaining: number): Promise<Photo[]> {
  if (remaining <= 0) return [];
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: true,
    selectionLimit: remaining,
    orderedSelection: true,
    quality: 0.8,
    // HEIC comes back as JPEG, which the agent can read.
    preferredAssetRepresentationMode:
      ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
  });
  if (result.canceled) return [];
  return result.assets
    .slice(0, remaining)
    .filter((asset) => (asset.fileSize ?? 0) <= MAX_PHOTO_BYTES)
    .map((asset, index) => ({
      id: `${Date.now()}-${index}`,
      uri: asset.uri,
      name: asset.fileName ?? `photo-${index + 1}.jpg`,
      mimeType: asset.mimeType ?? "image/jpeg",
      size: asset.fileSize ?? 0,
    }));
}

function uploadRequests(photos: Photo[]): TaskArtifactUploadRequest[] {
  return photos.map((photo) => ({
    name: photo.name,
    type: "user_attachment",
    source: "posthog_code",
    size: photo.size,
    content_type: photo.mimeType,
  }));
}

// Streams each file straight from disk to object storage; nothing is base64 encoded.
async function postFiles(
  photos: Photo[],
  prepared: PreparedTaskArtifactUpload[],
): Promise<void> {
  await Promise.all(
    prepared.map(async (artifact, index) => {
      const photo = photos[index];
      const form = new FormData();
      for (const [key, value] of Object.entries(
        artifact.presigned_post.fields,
      )) {
        form.append(key, value);
      }
      form.append("file", {
        uri: photo.uri,
        name: photo.name,
        type: photo.mimeType,
      } as unknown as Blob);
      const response = await fetch(artifact.presigned_post.url, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error(`Could not upload ${photo.name}`);
    }),
  );
}

// Photos for a task that has no run yet; the run picks them up when it starts.
export async function uploadStagedPhotos(
  taskId: string,
  photos: Photo[],
): Promise<string[]> {
  if (!photos.length) return [];
  const client = getClient();
  const prepared = await client.prepareTaskStagedArtifactUploads(
    taskId,
    uploadRequests(photos),
  );
  await postFiles(photos, prepared);
  const finalized = await client.finalizeTaskStagedArtifactUploads(
    taskId,
    prepared,
  );
  return finalized.map((artifact) => artifact.id);
}

export async function uploadRunPhotos(
  taskId: string,
  runId: string,
  photos: Photo[],
): Promise<string[]> {
  if (!photos.length) return [];
  const client = getClient();
  const prepared = await client.prepareTaskRunArtifactUploads(
    taskId,
    runId,
    uploadRequests(photos),
  );
  await postFiles(photos, prepared);
  const finalized = await client.finalizeTaskRunArtifactUploads(
    taskId,
    runId,
    prepared,
  );
  return finalized.map((artifact) => artifact.id);
}
