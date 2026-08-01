// Mirrors the artifact-ref parsing in @posthog/core/sessions/promptContent;
// mobile does not depend on @posthog/core, so the two are kept in sync by hand.
import { getFileName, isRasterImageFile } from "@posthog/shared";
import type {
  CloudArtifactRef,
  SessionEvent,
  SessionNotificationAttachment,
} from "../types";

interface PromptContentBlock {
  type?: string;
  text?: string;
  uri?: string;
  name?: string;
  resource?: { uri?: string };
  _meta?: { ui?: { hidden?: boolean } };
}

interface PromptMessage {
  method?: string;
  params?: { prompt?: PromptContentBlock[] };
}

export interface PromptAttachmentGroup {
  text: string;
  attachments: SessionNotificationAttachment[];
}

// Cloud attachment bytes are uploaded as run artifacts and referenced from the
// stored prompt as `file://…/.posthog/attachments/<runId>/<artifactId>/<file>`.
export function parseCloudArtifactRef(
  pathname: string,
): CloudArtifactRef | undefined {
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

function blockUri(
  block: PromptContentBlock,
): { uri: string; name?: string } | null {
  switch (block.type) {
    case "resource":
      return block.resource?.uri ? { uri: block.resource.uri } : null;
    case "image":
      return block.uri ? { uri: block.uri } : null;
    case "resource_link":
      return block.uri ? { uri: block.uri, name: block.name } : null;
    default:
      return null;
  }
}

function attachmentFromBlock(
  block: PromptContentBlock,
): SessionNotificationAttachment | null {
  const ref = blockUri(block);
  if (!ref || !ref.uri.startsWith("file://")) return null;

  let pathname: string;
  try {
    pathname = decodeURIComponent(new URL(ref.uri).pathname);
  } catch {
    return null;
  }

  const cloudArtifact = parseCloudArtifactRef(pathname);
  if (!cloudArtifact) return null;

  const fileName = ref.name?.trim() || getFileName(pathname) || "attachment";
  return {
    kind: isRasterImageFile(fileName) ? "image" : "document",
    uri: ref.uri,
    fileName,
    cloudArtifact,
  };
}

export function extractSessionPromptAttachments(
  message: unknown,
): PromptAttachmentGroup | null {
  const msg = message as PromptMessage | undefined;
  if (msg?.method !== "session/prompt") return null;
  const prompt = msg.params?.prompt;
  if (!Array.isArray(prompt)) return null;

  const textParts: string[] = [];
  const attachments: SessionNotificationAttachment[] = [];
  for (const block of prompt) {
    if (block.type === "text") {
      if (block._meta?.ui?.hidden) continue;
      if (typeof block.text === "string") textParts.push(block.text);
      continue;
    }
    const attachment = attachmentFromBlock(block);
    if (attachment) attachments.push(attachment);
  }

  if (attachments.length === 0) return null;
  return { text: textParts.join(""), attachments };
}

/**
 * S3-backed snapshots replay user turns as text-only `user_message_chunk`
 * events, dropping the attachment metadata. The `session/prompt` requests in the
 * same log still carry the cloud artifact references, so reattach them by
 * matching prompt text (FIFO on ties) to keep historical images renderable.
 */
export function reinjectPromptAttachments(events: SessionEvent[]): void {
  const pending: PromptAttachmentGroup[] = [];
  for (const event of events) {
    if (event.type === "acp_message") {
      const group = extractSessionPromptAttachments(event.message);
      if (group) pending.push(group);
      continue;
    }
    const update = event.notification?.update;
    if (update?.sessionUpdate !== "user_message_chunk") continue;
    if (update.attachments && update.attachments.length > 0) continue;
    const text = update.content?.text ?? "";
    const idx = pending.findIndex((group) => group.text === text);
    if (idx < 0) continue;
    update.attachments = pending[idx].attachments;
    pending.splice(idx, 1);
  }
}
