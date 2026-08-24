import { hasProseBeyondAttachments } from "@posthog/core/editor/cloud-prompt";
import {
  formatAttachmentSnippet,
  readAttachmentSnippets,
} from "@posthog/core/files/attachmentText";
import type { FileReadClient } from "@posthog/core/files/identifiers";
import { xmlToContent } from "@posthog/core/message-editor/content";

/**
 * Build the text the server should name a task from, when the description has no
 * prose of its own.
 *
 * Pasting a block of text into the composer stores it as a `pasted-text.txt`
 * attachment, so the description reaching the API is only an `Attached files:`
 * summary (cloud) or a bare `<file />` tag (local). Naming a task from that alone
 * gives "Untitled". This reads the head of each attachment and returns it as a
 * separate naming source, leaving the description (the agent prompt, and the key
 * the reload transcript dedup matches on) untouched.
 *
 * Returns `undefined` when the description already carries prose, so the server
 * names from the description as before.
 */
export async function buildTaskNamingSource(
  description: string,
  filePaths: string[],
  fileReadClient: FileReadClient,
): Promise<string | undefined> {
  if (
    filePaths.length === 0 ||
    hasProseBeyondAttachments(xmlToContent(description))
  ) {
    return undefined;
  }

  const snippets = await readAttachmentSnippets(filePaths, fileReadClient);
  const namingSource = snippets.map(formatAttachmentSnippet).join("\n\n");

  return namingSource.trim() ? namingSource : undefined;
}
