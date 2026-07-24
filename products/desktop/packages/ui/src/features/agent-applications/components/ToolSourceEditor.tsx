import { CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import type { ToolCompileError } from "@posthog/shared/agent-platform-types";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Text, TextArea } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";
import { useSaveRevisionTool } from "../hooks/useSaveRevisionTool";

/**
 * Editable source for one custom tool on a draft revision, with a Save that
 * compiles server-side. A compile failure (HTTP 422) comes back as a typed
 * result, not an error, so we render each {@link ToolCompileError} inline
 * (message + 1-based line/column) and DON'T mark the edit as saved. `description`
 * and `args_schema` are preserved from the tool's existing schema.json — v0 edits
 * source only.
 */
export function ToolSourceEditor({
  idOrSlug,
  revisionId,
  toolId,
  source,
  description,
  argsSchema,
}: {
  idOrSlug: string;
  revisionId: string;
  toolId: string;
  source: string;
  description: string;
  argsSchema: Record<string, unknown>;
}) {
  const save = useSaveRevisionTool(idOrSlug, revisionId);
  // The textarea is uncontrolled (seeded from `source` via defaultValue); the
  // parent keys this component by revision+tool, so switching either remounts it
  // with a fresh buffer. We track only whether it diverges from `source`.
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<ToolCompileError[] | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  // Clear the transient "saved" tick on unmount (or before the next save) so a
  // stale timer can't fire setState after the component is gone.
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    },
    [],
  );

  function onSave() {
    const draft = textareaRef.current?.value ?? source;
    setJustSaved(false);
    if (savedTimer.current) clearTimeout(savedTimer.current);
    save.mutate(
      {
        toolId,
        body: { description, args_schema: argsSchema, source: draft },
      },
      {
        onSuccess: (result) => {
          if (result.ok) {
            // Persisted — the buffer now matches the saved source.
            setErrors(null);
            setDirty(false);
            setJustSaved(true);
            savedTimer.current = setTimeout(() => setJustSaved(false), 2000);
          } else {
            // Compile failed — nothing persisted; surface the diagnostics.
            setErrors(result.errors);
          }
        },
      },
    );
  }

  function onRevert() {
    if (textareaRef.current) textareaRef.current.value = source;
    setDirty(false);
    setErrors(null);
  }

  return (
    <Flex direction="column" gap="2" className="mt-1.5">
      <TextArea
        ref={textareaRef}
        defaultValue={source}
        onChange={(e) => {
          setDirty(e.target.value !== source);
          if (justSaved) setJustSaved(false);
        }}
        rows={16}
        spellCheck={false}
        className="text-[12px] [font-family:var(--font-mono)]"
      />

      {errors && errors.length > 0 ? (
        <div className="rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-3 py-2">
          <Flex align="center" gap="1.5" className="text-(--red-11)">
            <WarningCircleIcon size={13} />
            <Text className="font-medium text-[12px]">
              {errors.length} compile error{errors.length > 1 ? "s" : ""} — not
              saved
            </Text>
          </Flex>
          <Flex direction="column" gap="1.5" className="mt-2">
            {errors.map((err) => (
              <div
                key={`${err.kind}:${err.line ?? ""}:${err.column ?? ""}:${err.message}`}
                className="rounded-(--radius-1) border border-border bg-(--color-panel-solid) px-2 py-1.5"
              >
                <Flex align="baseline" gap="2">
                  <Text className="text-(--red-11) text-[10.5px] uppercase tracking-wide [font-family:var(--font-mono)]">
                    {err.kind}
                  </Text>
                  {err.line != null ? (
                    <Text className="text-[10.5px] text-gray-10 [font-family:var(--font-mono)]">
                      line {err.line}
                      {err.column != null ? `:${err.column}` : ""}
                    </Text>
                  ) : null}
                </Flex>
                <Text className="mt-0.5 block text-[12px] text-gray-12 leading-snug">
                  {err.message}
                </Text>
              </div>
            ))}
          </Flex>
        </div>
      ) : null}

      {save.isError ? (
        <Text className="text-(--red-11) text-[11px]">
          {save.error?.message ?? "Couldn't save the tool."}
        </Text>
      ) : null}

      <Flex align="center" gap="2">
        <Button
          size="1"
          color="green"
          onClick={onSave}
          disabled={save.isPending || !dirty}
          loading={save.isPending}
        >
          {save.isPending ? "Compiling…" : "Save"}
        </Button>
        {dirty && !save.isPending ? (
          <Button size="1" variant="soft" color="gray" onClick={onRevert}>
            Revert
          </Button>
        ) : null}
        {justSaved ? (
          <Flex align="center" gap="1" className="text-(--green-11)">
            <CheckCircleIcon size={14} />
            <Text className="text-[12px]">Saved & compiled</Text>
          </Flex>
        ) : null}
      </Flex>

      {save.data?.ok ? (
        <div className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2">
          <Text className="block text-[11px] text-gray-10 uppercase tracking-wide [font-family:var(--font-mono)]">
            Capabilities
          </Text>
          <Text className="mt-1 block text-[12px] text-gray-11 leading-snug">
            {save.data.capabilities.secret_refs.length > 0
              ? `Secrets referenced: ${save.data.capabilities.secret_refs.join(", ")}`
              : "No secret references detected."}
          </Text>
          {save.data.capabilities.dynamic_secret_refs ? (
            <Text className="mt-0.5 block text-[11px] text-amber-11 leading-snug">
              This tool derives secret names dynamically — they can't be fully
              enumerated ahead of time.
            </Text>
          ) : null}
        </div>
      ) : null}

      <Text className="text-[11px] text-gray-10 leading-snug">
        Saving compiles the tool on the server. Only a clean compile persists.
      </Text>
    </Flex>
  );
}
