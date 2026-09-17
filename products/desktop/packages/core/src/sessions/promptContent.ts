import type { ContentBlock } from "@agentclientprotocol/sdk";
import {
  getFileName,
  isClipboardAttachmentPath,
  isRasterImageFile,
  pathToFileUri,
  unescapeXmlAttr,
} from "@posthog/shared";
import {
  ABSOLUTE_FILE_TAG_REGEX,
  normalizePromptText,
  stripAttachmentSummaryOf,
} from "../editor/cloud-prompt";

const ATTACHMENT_URI_PREFIX = "attachment://";

function hashAttachmentPath(filePath: string): string {
  let hash = 2166136261;

  for (let i = 0; i < filePath.length; i++) {
    hash ^= filePath.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }

  return (hash >>> 0).toString(36);
}

export function makeAttachmentUri(filePath: string): string {
  const label = encodeURIComponent(getFileName(filePath));
  const id = hashAttachmentPath(filePath);
  return `${ATTACHMENT_URI_PREFIX}${id}?label=${label}`;
}

export interface AttachmentRef {
  id: string;
  label: string;
  previewUrl?: string;
  cloudArtifact?: CloudArtifactRef;
}

export interface CloudArtifactRef {
  runId: string;
  artifactId: string;
}

function parseCloudArtifactRef(pathname: string): CloudArtifactRef | undefined {
  const segments = pathname.split("/").filter(Boolean);
  const posthogIndex = segments.lastIndexOf(".posthog");
  if (
    posthogIndex < 0 ||
    segments[posthogIndex + 1] !== "attachments" ||
    !segments[posthogIndex + 2] ||
    !segments[posthogIndex + 3]
  ) {
    return undefined;
  }

  return {
    runId: segments[posthogIndex + 2],
    artifactId: segments[posthogIndex + 3],
  };
}

export function parseAttachmentUri(uri: string): AttachmentRef | null {
  if (!uri.startsWith(ATTACHMENT_URI_PREFIX)) {
    return null;
  }

  const rawValue = uri.slice(ATTACHMENT_URI_PREFIX.length);
  const queryStart = rawValue.indexOf("?");
  if (queryStart < 0) {
    return null;
  }

  const label =
    decodeURIComponent(
      new URLSearchParams(rawValue.slice(queryStart + 1)).get("label") ?? "",
    ) || "attachment";

  return { id: uri, label };
}

function parseFileUri(
  uri: string,
  fallbackLabel?: string,
): AttachmentRef | null {
  if (!uri.startsWith("file://")) {
    return null;
  }

  try {
    const pathname = decodeURIComponent(new URL(uri).pathname);
    const label =
      fallbackLabel?.trim() || getFileName(pathname) || "attachment";
    const cloudArtifact = parseCloudArtifactRef(pathname);
    return { id: uri, label, ...(cloudArtifact ? { cloudArtifact } : {}) };
  } catch {
    const label = fallbackLabel?.trim() || getFileName(uri) || "attachment";
    return { id: uri, label };
  }
}

function getBlockAttachmentRef(block: ContentBlock): AttachmentRef | null {
  if (block.type === "resource") {
    const uri = block.resource.uri;
    if (!uri) {
      return null;
    }

    return parseAttachmentUri(uri) ?? parseFileUri(uri);
  }

  if (block.type === "image") {
    const image = block as typeof block & {
      data?: string;
      fileName?: string;
      mimeType?: string;
      uri?: string;
    };
    if (image.uri) {
      return parseAttachmentUri(image.uri) ?? parseFileUri(image.uri);
    }
    if (!image.data || !image.mimeType) {
      return null;
    }

    const extensionByMimeType: Record<string, string> = {
      "image/gif": "gif",
      "image/jpeg": "jpg",
      "image/png": "png",
      "image/webp": "webp",
    };
    const extension = extensionByMimeType[image.mimeType];
    if (!extension) {
      return null;
    }
    const id = `inline-image:${hashAttachmentPath(`${image.mimeType}:${image.data}`)}`;
    return {
      id,
      label: image.fileName || `image.${extension}`,
      previewUrl: `data:${image.mimeType};base64,${image.data}`,
    };
  }

  if (block.type === "resource_link") {
    return parseAttachmentUri(block.uri) ?? parseFileUri(block.uri, block.name);
  }

  return null;
}

export interface PromptDisplayContent {
  text: string;
  attachments: AttachmentRef[];
}

export function extractPromptDisplayContent(
  blocks: ContentBlock[],
  options?: { filterHidden?: boolean },
): PromptDisplayContent {
  const filterHidden = options?.filterHidden ?? false;

  const textParts: string[] = [];
  for (const block of blocks) {
    if (block.type !== "text") continue;
    if (filterHidden) {
      const meta = (block as { _meta?: { ui?: { hidden?: boolean } } })._meta;
      if (meta?.ui?.hidden) continue;
    }
    textParts.push(block.text);
  }

  const seen = new Set<string>();
  const attachments: AttachmentRef[] = [];
  for (const block of blocks) {
    const ref = getBlockAttachmentRef(block);
    if (!ref || seen.has(ref.id)) continue;
    const { id } = ref;
    if (!id) continue;
    seen.add(id);
    attachments.push(ref);
  }

  return { text: textParts.join(""), attachments };
}

const MENTION_TAG_TEST =
  /<(?:file\s+path|folder\s+path|github_issue\s+number|github_pr\s+number|error_context\s+label)="[^"]+"/;
export const SLASH_COMMAND_START = /^\/([a-zA-Z][\w-]*)(?=\s|$)/;

export function hasMentionTags(content: string): boolean {
  return MENTION_TAG_TEST.test(content) || SLASH_COMMAND_START.test(content);
}

export function resolveMessageAttachments(
  text: string,
  attachments: AttachmentRef[],
): PromptDisplayContent {
  const lifted = extractImageFileTags(text);
  // contentToXml folds every attachment into a <file /> mention, so text that
  // still carries one already lists the message's attachments inline.
  const visible = hasMentionTags(lifted.text)
    ? lifted.attachments
    : [
        ...attachments,
        ...lifted.attachments.filter(
          (image) => !attachments.some(({ id }) => id === image.id),
        ),
      ];
  return {
    text: stripAttachmentSummaryOf(
      lifted.text,
      new Set(visible.map(({ label }) => label)),
    ),
    attachments: visible,
  };
}

function extractImageFileTags(text: string): PromptDisplayContent {
  const attachments: AttachmentRef[] = [];
  const stripped = text.replace(
    ABSOLUTE_FILE_TAG_REGEX,
    (tag, rawPath: string) => {
      const filePath = unescapeXmlAttr(rawPath);
      const label = getFileName(filePath);
      // Message text is not trusted: only files the composer saved may be read from disk.
      if (!isClipboardAttachmentPath(filePath) || !isRasterImageFile(label)) {
        return tag;
      }
      const id = pathToFileUri(filePath);
      if (!attachments.some((attachment) => attachment.id === id)) {
        attachments.push({ id, label });
      }
      return "";
    },
  );
  if (attachments.length === 0) return { text, attachments };
  return { text: normalizePromptText(stripped), attachments };
}
