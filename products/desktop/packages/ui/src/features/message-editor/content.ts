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
  isContentEmpty,
  xmlToContent,
  xmlToPlainText,
} from "@posthog/core/message-editor/content";
