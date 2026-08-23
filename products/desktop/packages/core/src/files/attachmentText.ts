import { getFileName, isBinaryFile } from "@posthog/shared";
import type { FileReadClient } from "./identifiers";

/** Enough of an attachment to name a task after, without bloating the prompt. */
export const ATTACHMENT_SNIPPET_LIMIT = 500;

export interface AttachmentSnippet {
  fileName: string;
  /** Head of the file, or null when it is binary or could not be read. */
  text: string | null;
}

export async function readAttachmentSnippets(
  filePaths: string[],
  fileReadClient: FileReadClient,
): Promise<AttachmentSnippet[]> {
  return Promise.all(
    filePaths.map(async (filePath) => {
      const fileName = getFileName(filePath);
      if (isBinaryFile(filePath)) {
        return { fileName, text: null };
      }
      try {
        const content = await fileReadClient.readAbsoluteFile(filePath);
        return {
          fileName,
          text: content ? content.slice(0, ATTACHMENT_SNIPPET_LIMIT) : null,
        };
      } catch {
        return { fileName, text: null };
      }
    }),
  );
}

export function formatAttachmentSnippet(snippet: AttachmentSnippet): string {
  // Fall back to the file name for a binary, unreadable, or blank attachment: a
  // name reads better than nothing when it is all we have to title a task with.
  return snippet.text?.trim()
    ? snippet.text
    : `[Attached: ${snippet.fileName}]`;
}
