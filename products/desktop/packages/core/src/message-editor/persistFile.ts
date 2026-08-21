import { getImageMimeType, isRasterImageFile } from "@posthog/shared";
import type { FileAttachment } from "./content";

const CHUNK_SIZE = 8192;

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunks: string[] = [];
  for (let i = 0; i < bytes.length; i += CHUNK_SIZE) {
    chunks.push(String.fromCharCode(...bytes.subarray(i, i + CHUNK_SIZE)));
  }
  return btoa(chunks.join(""));
}

export interface PersistedFile {
  path: string;
  name: string;
  mimeType?: string;
}

export interface FilePersistHost {
  saveClipboardImage(input: {
    base64Data: string;
    mimeType: string;
    originalName: string;
  }): Promise<{ path: string; name: string; mimeType: string }>;
  saveClipboardText(input: {
    text: string;
    originalName?: string;
  }): Promise<{ path: string; name: string }>;
  saveClipboardFile(input: {
    base64Data: string;
    originalName: string;
  }): Promise<{ path: string; name: string }>;
  downscaleImageFile(input: {
    filePath: string;
  }): Promise<{ path: string; name: string }>;
}

export async function persistImageFile(
  host: FilePersistHost,
  file: File,
): Promise<PersistedFile> {
  const arrayBuffer = await file.arrayBuffer();
  const base64Data = arrayBufferToBase64(arrayBuffer);
  const mimeType = file.type || getImageMimeType(file.name);

  const result = await host.saveClipboardImage({
    base64Data,
    mimeType,
    originalName: file.name,
  });
  return { path: result.path, name: result.name, mimeType: result.mimeType };
}

export async function persistTextContent(
  host: FilePersistHost,
  text: string,
  originalName?: string,
): Promise<PersistedFile> {
  const result = await host.saveClipboardText({ text, originalName });
  return { path: result.path, name: result.name };
}

export async function persistGenericFile(
  host: FilePersistHost,
  file: File,
): Promise<PersistedFile> {
  const arrayBuffer = await file.arrayBuffer();
  const base64Data = arrayBufferToBase64(arrayBuffer);

  const result = await host.saveClipboardFile({
    base64Data,
    originalName: file.name,
  });

  return {
    path: result.path,
    name: result.name,
    mimeType: file.type || undefined,
  };
}

export async function persistImageFilePath(
  host: FilePersistHost,
  filePath: string,
): Promise<{ id: string; label: string }> {
  const result = await host.downscaleImageFile({ filePath });
  return { id: result.path, label: result.name };
}

export interface ResolveDroppedFileOptions {
  onDownscaleFailed?: () => void;
}

export async function resolveDroppedFile(
  host: FilePersistHost,
  file: File,
  filePath: string | null,
  options?: ResolveDroppedFileOptions,
): Promise<FileAttachment | null> {
  if (!filePath) return null;

  if (isRasterImageFile(file.name)) {
    try {
      return await persistImageFilePath(host, filePath);
    } catch {
      options?.onDownscaleFailed?.();
      return { id: filePath, label: file.name };
    }
  }

  return { id: filePath, label: file.name };
}

export async function persistBrowserFile(
  host: FilePersistHost,
  file: File,
): Promise<{ id: string; label: string }> {
  if (file.type.startsWith("image/")) {
    const result = await persistImageFile(host, file);
    return { id: result.path, label: result.name };
  }

  const result = await persistGenericFile(host, file);
  return { id: result.path, label: result.name };
}
