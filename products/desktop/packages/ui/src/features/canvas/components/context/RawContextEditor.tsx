import { Button, Text, Textarea } from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";

interface RawContextEditorProps {
  content: string;
  onSave: (content: string) => Promise<void>;
  isSaving: boolean;
}

/** The whole CONTEXT.md as one markdown file, for people who want the source. */
export function RawContextEditor({
  content,
  onSave,
  isSaving,
}: RawContextEditorProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const editing = draft !== null;

  const save = async () => {
    if (draft === null) return;
    await onSave(draft);
    setDraft(null);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <Text size="xs" variant="muted">
          {editing
            ? "Editing the source. Managed sections are rewritten in their fixed shape when you save from the overview."
            : "This is exactly what agents receive. Sections written by the overview keep a fixed shape."}
        </Text>
        <div className="flex shrink-0 items-center gap-2">
          {editing ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDraft(null)}
                disabled={isSaving}
              >
                Discard
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={save}
                disabled={isSaving || draft === content}
              >
                {isSaving ? <Spinner /> : null}
                Save
              </Button>
            </>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDraft(content)}
            >
              Edit source
            </Button>
          )}
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {editing ? (
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={isSaving}
            autoFocus
            spellCheck={false}
            placeholder="# Space context…"
            className="min-h-[60vh] resize-y rounded-none border-0 font-mono text-xs leading-relaxed focus-visible:ring-0"
          />
        ) : content.trim() ? (
          <div className="px-5 py-4 text-xs leading-relaxed">
            <MarkdownRenderer content={content} />
          </div>
        ) : (
          <div className="px-5 py-8 text-center">
            <Text size="xs" variant="muted">
              CONTEXT.md is empty.
            </Text>
          </div>
        )}
      </div>
    </div>
  );
}
