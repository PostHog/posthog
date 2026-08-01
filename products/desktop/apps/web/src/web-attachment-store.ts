// In-memory attachment byte store for the web host.
//
// The composer produces a FileAttachment { id, label } and the cloud-upload
// pipeline later reads the bytes back (id -> base64). On desktop the id is a
// real filesystem path written by the os.saveClipboard* handlers (Node fs) and
// read back by fs.readFileAsBase64.
//
// A browser has no filesystem, but the id is opaque — so on web the
// os.saveClipboard* handlers stash the browser-computed base64 here under a
// synthetic id, and the web fs.readFileAsBase64 / os.readFileAsDataUrl handlers
// read it back. The entire presigned-POST upload pipeline in CloudArtifactService
// is already portable and needs no changes.
//
// The synthetic id ends in the original filename (…/<uuid>/<name>) on purpose:
// the cloud pipeline derives the attachment's kind and upload name from the
// PATH via getFileName/inferContentType (isClaudeImageFile, isRasterImageFile,
// isTextAttachment). Without the extension there, a dropped/pasted image would
// upload as an extension-less blob the agent can't recognize, and the composer's
// image preview (which reads by id) would fail.
//
// Bytes live only for the lifetime of the tab; an attachment is uploaded to the
// cloud run shortly after it's added, so there's no need to persist them.

interface StoredAttachment {
  base64Data: string;
  name: string;
  mimeType?: string;
}

const attachments = new Map<string, StoredAttachment>();

function safeName(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? "";
  return base.length > 0 ? base : "file";
}

/** Store attachment bytes and return the synthetic id used as FileAttachment.id. */
export function putWebAttachment(entry: StoredAttachment): {
  path: string;
  name: string;
  mimeType?: string;
} {
  // Leading slash so the id reads as an absolute path (the cloud-prompt
  // transport only keeps <file path> tags that pass isAbsolutePath); trailing
  // filename so getFileName(id) yields a name with its extension for the
  // cloud-upload kind/name derivation and the preview.
  const id = `/web-attachment/${crypto.randomUUID()}/${safeName(entry.name)}`;
  attachments.set(id, entry);
  return { path: id, name: entry.name, mimeType: entry.mimeType };
}

/** Read attachment bytes back as base64 for cloud upload (null if unknown). */
export function getWebAttachmentBase64(id: string): string | null {
  return attachments.get(id)?.base64Data ?? null;
}

/** Build a data URL for an attachment (used by the composer image preview). */
export function getWebAttachmentDataUrl(id: string): string | null {
  const entry = attachments.get(id);
  if (!entry) return null;
  const mimeType = entry.mimeType ?? "application/octet-stream";
  return `data:${mimeType};base64,${entry.base64Data}`;
}
