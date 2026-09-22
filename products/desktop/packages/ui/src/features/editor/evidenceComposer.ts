import {
  type EditorContent,
  isContentEmpty,
  type PostHogObjectKind,
} from "@posthog/core/message-editor/content";

export function buildEvidenceComposerContent({
  kind,
  id,
  label,
  currentDraft,
}: {
  kind: PostHogObjectKind;
  id: string;
  label: string;
  currentDraft: EditorContent | string | null;
}): EditorContent {
  return {
    segments: [
      {
        type: "text",
        text: isContentEmpty(currentDraft) ? "Ask about " : "\n\nAsk about ",
      },
      {
        type: "chip",
        chip: { type: "posthog_object", objectKind: kind, id, label },
      },
      { type: "text", text: " " },
    ],
  };
}
