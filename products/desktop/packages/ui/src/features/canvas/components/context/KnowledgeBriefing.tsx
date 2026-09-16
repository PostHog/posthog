import { PencilSimpleIcon, PlusIcon, SparkleIcon } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMemo, useState } from "react";
import type { Components } from "react-markdown";

interface KnowledgeBriefingProps {
  knowledge: string;
  onSave: (knowledge: string) => Promise<void>;
  onAskAgent: () => void;
  isSaving: boolean;
  /** Open straight into the editor, seeded with the template. */
  startEditing?: boolean;
}

/** The parts agents look for. A chip appends the heading when it is missing. */
const SECTIONS = [
  {
    title: "What this is",
    hint: "The area, who it is for, what good looks like.",
  },
  {
    title: "How to work here",
    hint: "Conventions, review rules, how to test.",
  },
  { title: "Key files", hint: "The paths that matter, one line each." },
  { title: "Gotchas", hint: "What is not obvious from the code." },
];

const TEMPLATE = `## What this is

## How to work here

## Key files

## Gotchas
`;

// The briefing is a document, not a chat message: headings in the foreground
// with a real scale, and a readable measure.
const BRIEFING_COMPONENTS: Partial<Components> = {
  h1: ({ children }) => (
    <h2 className="mt-5 mb-2 font-semibold text-base text-foreground first:mt-0">
      {children}
    </h2>
  ),
  h2: ({ children }) => (
    <h3 className="mt-5 mb-1.5 font-semibold text-foreground text-sm first:mt-0">
      {children}
    </h3>
  ),
  h3: ({ children }) => (
    <h4 className="mt-4 mb-1 font-medium text-foreground text-xs first:mt-0">
      {children}
    </h4>
  ),
};

function missingSections(markdown: string): typeof SECTIONS {
  const headings = new Set(
    [...markdown.matchAll(/^##\s+(.+?)\s*$/gm)].map((m) => m[1].toLowerCase()),
  );
  return SECTIONS.filter((s) => !headings.has(s.title.toLowerCase()));
}

/**
 * The free text of CONTEXT.md, opened in place under its row. Reads as a
 * document; the tools to change it sit under the text, where a reader
 * arrives when done.
 */
export function KnowledgeBriefing({
  knowledge,
  onSave,
  onAskAgent,
  isSaving,
  startEditing = false,
}: KnowledgeBriefingProps) {
  const [draft, setDraft] = useState<string | null>(
    startEditing ? knowledge.trim() || TEMPLATE : null,
  );
  const editing = draft !== null;
  const missing = useMemo(
    () => (editing ? missingSections(draft) : missingSections(knowledge)),
    [editing, draft, knowledge],
  );

  const save = async () => {
    if (draft === null) return;
    await onSave(draft);
    setDraft(null);
  };

  const appendSection = (heading: string) => {
    const base = (draft ?? knowledge).replace(/\s+$/, "");
    setDraft(`${base}${base ? "\n\n" : ""}## ${heading}\n\n`);
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-2">
        <div className="h-[380px] overflow-hidden rounded-lg border border-border bg-background">
          <CodeMirrorEditor
            content={draft}
            filePath="CONTEXT.md"
            onContentChange={setDraft}
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {missing.length > 0 ? (
              <Text size="xxs" variant="muted" className="mr-1">
                Add a section
              </Text>
            ) : null}
            {missing.map((section) => (
              <Button
                key={section.title}
                variant="outline"
                size="xs"
                title={section.hint}
                onClick={() => appendSection(section.title)}
              >
                <PlusIcon size={11} />
                {section.title}
              </Button>
            ))}
          </div>
          <div className="flex items-center gap-1">
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
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="max-w-[68ch] text-xs leading-relaxed">
        <MarkdownRenderer
          content={knowledge}
          componentsOverride={BRIEFING_COMPONENTS}
        />
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="link-muted"
          size="xs"
          onClick={() => setDraft(knowledge)}
        >
          <PencilSimpleIcon size={12} />
          Edit
        </Button>
        <Button variant="link-muted" size="xs" onClick={onAskAgent}>
          <SparkleIcon size={12} />
          Update with agent
        </Button>
      </div>
    </div>
  );
}
