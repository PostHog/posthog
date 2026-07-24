import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { Dialog, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useImportAgentDraftBundle } from "../hooks/useImportAgentDraftBundle";
import { parseBundleInput } from "../utils/parseBundleInput";

const SAMPLE = `--- agent.md ---
You are the growth review agent. …

--- skills/research/SKILL.md ---
When asked to research, …

--- skills/draft-post/SKILL.md ---
When asked to draft, …
`;

/**
 * Bulk-paste a markdown bundle into a draft revision. Designed for migrating
 * an existing multi-file agent in one paste — concatenate the source files
 * with a `--- path ---` header between each. Existing skill ids are
 * overwritten; new ids are added; skills not mentioned are left alone.
 */
export function AgentBundleImportDialog({
  open,
  onOpenChange,
  idOrSlug,
  revisionId,
  existingSkillIds,
  onSuccess,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  idOrSlug: string;
  revisionId: string;
  existingSkillIds: string[];
  onSuccess?: () => void;
}) {
  const [input, setInput] = useState("");
  const mutation = useImportAgentDraftBundle(idOrSlug, revisionId);

  const parsed = useMemo(() => {
    if (input.trim().length === 0) return null;
    return parseBundleInput(input);
  }, [input]);

  const value = parsed?.ok ? parsed.value : null;
  const existing = useMemo(() => new Set(existingSkillIds), [existingSkillIds]);

  const onConfirm = () => {
    if (!value) return;
    mutation.mutate(value, {
      onSuccess: () => {
        setInput("");
        mutation.reset();
        onOpenChange(false);
        onSuccess?.();
      },
    });
  };

  const close = () => {
    if (mutation.isPending) return;
    setInput("");
    mutation.reset();
    onOpenChange(false);
  };

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) close();
      }}
    >
      <Dialog.Content maxWidth="640px">
        <Dialog.Title className="text-base">Paste markdown bundle</Dialog.Title>
        <Dialog.Description size="2" className="text-gray-11">
          Paste one or more <code>--- path ---</code> blocks. Accepts{" "}
          <code>agent.md</code> and <code>skills/[id]/SKILL.md</code>. Existing
          skills are overwritten by id; new ids are added.
        </Dialog.Description>
        <textarea
          aria-label="Markdown bundle"
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          placeholder={SAMPLE}
          disabled={mutation.isPending}
          spellCheck={false}
          className="mt-3 min-h-[280px] w-full resize-y rounded-(--radius-2) border border-border bg-(--color-panel-solid) p-3 text-[12.5px] text-gray-12 [font-family:var(--font-mono)] focus:border-(--accent-7) focus:outline-none"
        />
        {parsed && !parsed.ok ? (
          <Text className="mt-2 block text-(--red-11) text-[12px]">
            {parsed.error}
          </Text>
        ) : null}
        {value ? (
          <div className="mt-3 rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2">
            <Text className="block text-[11px] text-gray-10 uppercase tracking-wide">
              Will write
            </Text>
            <Flex direction="column" gap="1" className="mt-1.5">
              {value.agent_md !== undefined ? (
                <Flex align="center" gap="2">
                  <code className="text-[12px] text-gray-12 [font-family:var(--font-mono)]">
                    agent.md
                  </code>
                  <Badge color="blue">update</Badge>
                </Flex>
              ) : null}
              {value.skills?.map((s) => (
                <Flex key={s.id} align="center" gap="2">
                  <code className="text-[12px] text-gray-12 [font-family:var(--font-mono)]">
                    skills/{s.id}/SKILL.md
                  </code>
                  <Badge color={existing.has(s.id) ? "blue" : "green"}>
                    {existing.has(s.id) ? "update" : "new"}
                  </Badge>
                </Flex>
              ))}
            </Flex>
          </div>
        ) : null}
        {mutation.isError ? (
          <Text className="mt-2 block text-(--red-11) text-[12px]">
            {mutation.error?.message ?? "Import failed"}
          </Text>
        ) : null}
        <Flex justify="end" gap="2" mt="4">
          <Button
            size="1"
            variant="soft"
            color="gray"
            disabled={mutation.isPending}
            onClick={close}
          >
            Cancel
          </Button>
          <Button
            size="1"
            loading={mutation.isPending}
            disabled={!value}
            onClick={onConfirm}
          >
            Import
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
