import { PencilSimpleIcon, SparkleIcon } from "@phosphor-icons/react";
import { Button, Text, Textarea } from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";

interface KnowledgeBriefingProps {
  knowledge: string;
  onSave: (knowledge: string) => Promise<void>;
  onAskAgent: () => void;
  isSaving: boolean;
  /** Open straight into the editor, seeded with the template. */
  startEditing?: boolean;
}

const TEMPLATE = `# What this space is about

Describe the product area, who it is for, and what "good" looks like.

## How to work here

Conventions, key files, and the things that are not obvious from the code.
`;

/** The free text of CONTEXT.md, read as a document with the edit tools on hover. */
export function KnowledgeBriefing({
  knowledge,
  onSave,
  onAskAgent,
  isSaving,
  startEditing = false,
}: KnowledgeBriefingProps) {
  const [draft, setDraft] = useState<string | null>(
    startEditing ? TEMPLATE : null,
  );
  const editing = draft !== null;
  const hasKnowledge = knowledge.trim().length > 0;

  const save = async () => {
    if (draft === null) return;
    await onSave(draft);
    setDraft(null);
  };

  return (
    <section className="group/briefing flex min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          About this space
        </Text>
        <div className="flex items-center gap-1">
          {editing ? (
            <>
              <Button
                variant="outline"
                size="xs"
                onClick={() => setDraft(null)}
                disabled={isSaving}
              >
                Discard
              </Button>
              <Button
                variant="primary"
                size="xs"
                onClick={save}
                disabled={isSaving || draft === knowledge}
              >
                {isSaving ? <Spinner /> : null}
                Save
              </Button>
            </>
          ) : (
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-focus-within/briefing:opacity-100 group-hover/briefing:opacity-100">
              <Button variant="default" size="xs" onClick={onAskAgent}>
                <SparkleIcon size={13} />
                Update with agent
              </Button>
              <Button
                variant="default"
                size="xs"
                onClick={() => setDraft(hasKnowledge ? knowledge : TEMPLATE)}
              >
                <PencilSimpleIcon size={13} />
                Edit
              </Button>
            </div>
          )}
        </div>
      </div>

      {editing ? (
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={isSaving}
          autoFocus
          placeholder="Write markdown…"
          className="min-h-[360px] resize-y font-mono text-xs leading-relaxed"
        />
      ) : hasKnowledge ? (
        <div className="text-xs leading-relaxed">
          <MarkdownRenderer content={knowledge} />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setDraft(TEMPLATE)}
          className="rounded-lg border border-border border-dashed px-4 py-6 text-left transition-colors hover:bg-fill-hover"
        >
          <Text size="xs" weight="medium">
            Nothing written yet
          </Text>
          <Text size="xs" variant="muted">
            What this space is, the key files, and the things that are not
            obvious from the code. Click to write it, or update with an agent.
          </Text>
        </button>
      )}
    </section>
  );
}
