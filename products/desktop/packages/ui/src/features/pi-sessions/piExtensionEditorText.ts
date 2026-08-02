import {
  type EditorContent,
  textToContent,
} from "@posthog/core/message-editor/content";

export function piExtensionEditorTextToContent(text: string): EditorContent {
  return textToContent(text);
}
