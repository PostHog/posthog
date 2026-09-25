import { getImageMimeType, serializeCloudPrompt } from "@posthog/shared";
import { Platform } from "react-native";

export const MAX_PHOTOS = 3;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
]);

export interface PendingPhoto {
  id: string;
  uri: string;
  name: string;
  mimeType: string;
  jpegBase64?: string;
}

export async function pickPhoto(): Promise<PendingPhoto | null> {
  let ImagePicker: typeof import("expo-image-picker");
  try {
    ImagePicker = await import("expo-image-picker");
  } catch {
    throw new Error("Install a new build to attach photos.");
  }
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: false,
    quality: 0.8,
    exif: false,
    base64: Platform.OS === "ios",
  });
  if (result.canceled || !result.assets.length) return null;
  const asset = result.assets[0];
  const name = asset.fileName ?? "image.jpg";
  const mimeType = asset.mimeType ?? getImageMimeType(name);
  const jpegBase64 =
    !IMAGE_TYPES.has(mimeType) && Platform.OS === "ios"
      ? (asset.base64 ?? undefined)
      : undefined;
  if (!IMAGE_TYPES.has(mimeType) && !jpegBase64) {
    throw new Error("Choose a JPEG, PNG, GIF, or WebP image.");
  }
  if (
    (asset.fileSize && !jpegBase64 && asset.fileSize > MAX_IMAGE_BYTES) ||
    (jpegBase64 && Math.floor((jpegBase64.length * 3) / 4) > MAX_IMAGE_BYTES)
  ) {
    throw new Error("Choose an image smaller than 5 MB.");
  }
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    uri: asset.uri,
    name: jpegBase64 ? `${name.replace(/\.[^.]+$/, "")}.jpg` : name,
    mimeType: jpegBase64 ? "image/jpeg" : mimeType,
    jpegBase64,
  };
}

export async function buildPhotoPrompt(
  text: string,
  photos: PendingPhoto[],
): Promise<string> {
  const trimmed = text.trim();
  if (!photos.length) return trimmed;
  const FileSystem = await import("expo-file-system/legacy");
  const blocks: Parameters<typeof serializeCloudPrompt>[0] = [
    { type: "text", text: trimmed || "Please look at the attached image." },
  ];
  let totalBytes = 0;
  for (const photo of photos) {
    if (!photo.jpegBase64) {
      const info = await FileSystem.getInfoAsync(photo.uri);
      if (!info.exists)
        throw new Error(`${photo.name} is no longer available.`);
      if (info.size && totalBytes + info.size > MAX_IMAGE_BYTES) {
        throw new Error("Images must be under 5 MB in total.");
      }
    }
    const data =
      photo.jpegBase64 ??
      (await FileSystem.readAsStringAsync(photo.uri, {
        encoding: FileSystem.EncodingType.Base64,
      }));
    const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
    totalBytes += Math.floor((data.length * 3) / 4) - padding;
    if (totalBytes > MAX_IMAGE_BYTES) {
      throw new Error("Images must be under 5 MB in total.");
    }
    blocks.push({ type: "image", data, mimeType: photo.mimeType });
  }
  return serializeCloudPrompt(blocks);
}
