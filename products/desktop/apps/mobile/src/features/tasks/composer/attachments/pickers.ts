import { getImageMimeType } from "@posthog/shared";
import { Alert } from "react-native";
import { logger } from "@/lib/logger";
import type { PendingAttachment } from "./types";

const log = logger.scope("attachments");

function makeId(): string {
  return `att-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function inferImageMime(uri: string, mime?: string | null): string {
  if (mime) return mime;
  const detected = getImageMimeType(uri);
  return detected === "application/octet-stream" ? "image/jpeg" : detected;
}

function deriveFileName(uri: string, fallback: string): string {
  const last = uri.split("/").pop();
  if (last && last.length > 0) return decodeURIComponent(last.split("?")[0]);
  return fallback;
}

function showNativeModuleAlert(kind: "document" | "image"): void {
  const label = kind === "document" ? "file attachments" : "photo attachments";

  Alert.alert(
    "App update needed",
    `This build does not include the native module for ${label} yet. Rebuild and reinstall the mobile app on your device to use this feature.`,
  );
}

async function loadDocumentPicker(): Promise<
  typeof import("expo-document-picker") | null
> {
  try {
    return await import("expo-document-picker");
  } catch (err) {
    log.error("Document picker native module unavailable", err);
    showNativeModuleAlert("document");
    return null;
  }
}

async function loadImagePicker(): Promise<
  typeof import("expo-image-picker") | null
> {
  try {
    return await import("expo-image-picker");
  } catch (err) {
    log.error("Image picker native module unavailable", err);
    showNativeModuleAlert("image");
    return null;
  }
}

/**
 * Open the photo library and return the picked image as a PendingAttachment.
 * Returns `null` if the user cancels or permission is denied.
 */
export async function pickPhotoFromLibrary(): Promise<PendingAttachment | null> {
  const ImagePicker = await loadImagePicker();
  if (!ImagePicker) return null;

  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) {
    Alert.alert(
      "Photo access needed",
      "Allow PostHog to access your photos in Settings to attach images.",
    );
    return null;
  }

  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    quality: 0.8,
    allowsMultipleSelection: false,
    exif: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  return {
    kind: "image",
    id: makeId(),
    uri: asset.uri,
    fileName: asset.fileName ?? deriveFileName(asset.uri, "image.jpg"),
    mimeType: inferImageMime(asset.uri, asset.mimeType),
    sizeBytes: asset.fileSize,
  };
}

/**
 * Open the camera and return the captured photo as a PendingAttachment.
 */
export async function captureFromCamera(): Promise<PendingAttachment | null> {
  const ImagePicker = await loadImagePicker();
  if (!ImagePicker) return null;

  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) {
    Alert.alert(
      "Camera access needed",
      "Allow PostHog to use your camera in Settings to capture attachments.",
    );
    return null;
  }

  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["images"],
    quality: 0.8,
    exif: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  return {
    kind: "image",
    id: makeId(),
    uri: asset.uri,
    fileName: asset.fileName ?? deriveFileName(asset.uri, "photo.jpg"),
    mimeType: inferImageMime(asset.uri, asset.mimeType),
    sizeBytes: asset.fileSize,
  };
}

/**
 * Open the document picker for text/code files. Binary documents are accepted
 * by the picker but rejected at send-time by `buildCloudPromptBlocks` because
 * the cloud agent only supports text or image content.
 */
export async function pickDocument(): Promise<PendingAttachment | null> {
  try {
    const DocumentPicker = await loadDocumentPicker();
    if (!DocumentPicker) return null;

    const result = await DocumentPicker.getDocumentAsync({
      type: "*/*",
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled || result.assets.length === 0) return null;

    const asset = result.assets[0];
    return {
      kind: "document",
      id: makeId(),
      uri: asset.uri,
      fileName: asset.name,
      mimeType: asset.mimeType ?? "application/octet-stream",
      sizeBytes: asset.size,
    };
  } catch (err) {
    log.error("Document picker failed", err);
    return null;
  }
}
