export type {
  EditorContent,
  FileAttachment,
  MentionChip,
} from "@posthog/core/message-editor/content";
export {
  contentToPlainText,
  contentToXml,
  deriveFileLabel,
  extractFilePaths,
  extractFolderPaths,
  isContentEmpty,
  xmlToContent,
  xmlToPlainText,
} from "@posthog/core/message-editor/content";
