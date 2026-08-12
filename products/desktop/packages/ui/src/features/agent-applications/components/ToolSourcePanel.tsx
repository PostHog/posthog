import {
  CaretDownIcon,
  CaretRightIcon,
  PencilSimpleIcon,
  PlayIcon,
} from "@phosphor-icons/react";
import type { BundleFile } from "@posthog/shared/agent-platform-types";
import { Button } from "@posthog/ui/primitives/Button";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { ToolDryRunPanel } from "./ToolDryRunPanel";
import { ToolSourceEditor } from "./ToolSourceEditor";

/**
 * Read-first container for a custom tool's source. The resting state is a
 * collapsed, read-only view — editing and dry-run are explicit, opt-in toggles
 * so the surface never looks like a code editor bolted into the builder. The
 * parent keys this by revision+tool, so switching either resets the toggles.
 */
export function ToolSourcePanel({
  idOrSlug,
  revisionId,
  toolId,
  source,
  description,
  argsSchema,
  canEdit,
  canDryRun,
}: {
  idOrSlug: string;
  revisionId: string;
  toolId: string;
  source: BundleFile;
  description: string;
  argsSchema: Record<string, unknown>;
  /** Draft revision + flag: offer inline editing. */
  canEdit: boolean;
  /** Flag + custom tool: offer the dry-run panel. */
  canDryRun: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [testing, setTesting] = useState(false);

  return (
    <div className="mt-2">
      <Flex align="center" justify="between" gap="2">
        <Text className="block text-[11px] text-gray-10 uppercase tracking-wide [font-family:var(--font-mono)]">
          source · {source.path}
        </Text>
        <Flex align="center" gap="1">
          {!editing ? (
            <Button
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => setSourceOpen((v) => !v)}
            >
              {sourceOpen ? (
                <CaretDownIcon size={12} />
              ) : (
                <CaretRightIcon size={12} />
              )}
              {sourceOpen ? "Hide source" : "Show source"}
            </Button>
          ) : null}
          {canEdit ? (
            <Button
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => {
                setEditing((v) => !v);
                setSourceOpen(true);
              }}
            >
              {editing ? "Done" : <PencilSimpleIcon size={12} />}
              {editing ? "" : "Edit source"}
            </Button>
          ) : null}
        </Flex>
      </Flex>

      {editing ? (
        <ToolSourceEditor
          idOrSlug={idOrSlug}
          revisionId={revisionId}
          toolId={toolId}
          source={source.content}
          description={description}
          argsSchema={argsSchema}
        />
      ) : sourceOpen ? (
        <div className="mt-1.5">
          <CodeBlock>{source.content}</CodeBlock>
        </div>
      ) : (
        <Text className="mt-1 block text-[12px] text-gray-10 leading-snug">
          Source is hidden.{" "}
          {canEdit
            ? "Show it to read, or edit it inline."
            : "Show it to read the compiled tool."}
        </Text>
      )}

      {canDryRun ? (
        <div className="mt-3">
          {testing ? (
            <>
              <Flex justify="end" className="mb-1">
                <Button
                  size="1"
                  variant="ghost"
                  color="gray"
                  onClick={() => setTesting(false)}
                >
                  Hide test
                </Button>
              </Flex>
              <ToolDryRunPanel
                idOrSlug={idOrSlug}
                revisionId={revisionId}
                toolId={toolId}
              />
            </>
          ) : (
            <Button size="1" variant="soft" onClick={() => setTesting(true)}>
              <PlayIcon size={12} />
              Test tool
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
}
