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

/** Splits a leading `# Title` off the body so the section can wear it. */
function splitTitle(markdown: string): { title: string | null; body: string } {
  const match = /^\s*#\s+(.+?)\s*\n+([\s\S]*)$/.exec(markdown);
  if (!match) return { title: null, body: markdown };
  return { title: match[1], body: match[2] };
}

function missingSections(markdown: string): typeof SECTIONS {
  const headings = new Set(
    [...markdown.matchAll(/^##\s+(.+?)\s*$/gm)].map((m) => m[1].toLowerCase()),
  );
  return SECTIONS.filter((s) => !headings.has(s.title.toLowerCase()));
}

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
  const { title, body } = useMemo(() => splitTitle(knowledge), [knowledge]);
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

  return (
    <section className="group/briefing flex min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          {title && !editing ? title : "About"}
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
        <div className="flex flex-col gap-2">
          <div className="h-[420px] overflow-hidden rounded-lg border border-border bg-background">
            <CodeMirrorEditor
              content={draft}
              filePath="CONTEXT.md"
              onContentChange={setDraft}
            />
          </div>
          {missing.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <Text size="xxs" variant="muted" className="mr-1">
                Add a section
              </Text>
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
          ) : null}
        </div>
      ) : hasKnowledge ? (
        <div className="max-w-[68ch] text-xs leading-relaxed">
          <MarkdownRenderer
            content={body}
            componentsOverride={BRIEFING_COMPONENTS}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setDraft(TEMPLATE)}
          className="flex items-baseline gap-2 border-border border-y py-4 text-left transition-colors hover:bg-fill-hover"
        >
          <Text size="sm" weight="medium">
            Nothing written yet.
          </Text>
          <Text size="xs" variant="muted">
            Start from {SECTIONS.map((s) => s.title.toLowerCase()).join(", ")},
            or update with an agent.
          </Text>
        </button>
      )}
    </section>
  );
}
