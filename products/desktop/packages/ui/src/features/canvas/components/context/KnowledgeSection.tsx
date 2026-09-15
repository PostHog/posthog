import {
  BookOpenTextIcon,
  PencilSimpleIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import { Button, Text, Textarea } from "@posthog/quill";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";
import { SectionCard, SectionPlaceholder } from "./SectionCard";

interface KnowledgeSectionProps {
  channelId: string;
  channelName: string;
  knowledge: string;
  onSave: (knowledge: string) => Promise<void>;
  isSaving: boolean;
}

const TEMPLATE = `# What this space is about

Describe the product area, who it is for, and what "good" looks like.

## How to work here

Conventions, key files, and the things that are not obvious from the code.
`;

/** The free-form part of CONTEXT.md: what the space is, and how to work in it. */
export function KnowledgeSection({
  channelId,
  channelName,
  knowledge,
  onSave,
  isSaving,
}: KnowledgeSectionProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const editing = draft !== null;
  const hasKnowledge = knowledge.trim().length > 0;

  const save = async () => {
    if (draft === null) return;
    await onSave(draft);
    setDraft(null);
  };

  const actions = editing ? (
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
        disabled={isSaving || draft === knowledge}
      >
        {isSaving ? <Spinner /> : null}
        Save
      </Button>
    </>
  ) : hasKnowledge ? (
    <>
      <Button variant="outline" size="sm" onClick={() => setAgentOpen(true)}>
        <SparkleIcon size={14} />
        Refresh with agent
      </Button>
      <Button variant="outline" size="sm" onClick={() => setDraft(knowledge)}>
        <PencilSimpleIcon size={14} />
        Edit
      </Button>
    </>
  ) : null;

  return (
    <SectionCard
      icon={<BookOpenTextIcon size={16} />}
      title="Knowledge"
      description="What this space is about and how to work in it. Every agent reads this first."
      actions={actions}
    >
      {editing ? (
        <div className="flex flex-col">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={isSaving}
            autoFocus
            placeholder="Write markdown…"
            className="min-h-[320px] resize-y rounded-none border-0 font-mono text-xs leading-relaxed focus-visible:ring-0"
          />
          <div className="flex items-center justify-between gap-3 border-border border-t px-4 py-2">
            <Text size="xxs" variant="muted">
              Markdown. Links, objects, and goals are managed in the sections
              below and stay out of this text.
            </Text>
          </div>
        </div>
      ) : hasKnowledge ? (
        <div className="px-5 py-4 text-xs leading-relaxed">
          <MarkdownRenderer content={knowledge} />
        </div>
      ) : (
        <SectionPlaceholder>
          <Text size="xs" weight="medium">
            Nothing written yet
          </Text>
          <Text size="xs" variant="muted" className="max-w-[420px]">
            Give agents the specifics they need in {channelName}: what it is,
            key files, conventions, and gotchas.
          </Text>
          <div className="mt-2 flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => setDraft(TEMPLATE)}
            >
              <PencilSimpleIcon size={14} />
              Write it myself
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAgentOpen(true)}
            >
              <SparkleIcon size={14} />
              Build with agent
            </Button>
          </div>
        </SectionPlaceholder>
      )}
      <CreateChannelModal
        open={agentOpen}
        onOpenChange={setAgentOpen}
        existingContext={{ channelId, channelName }}
      />
    </SectionCard>
  );
}
