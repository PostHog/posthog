import { canvasV2ToolName } from "@posthog/core/canvas-v2/toolCalls";
import { Badge, Text } from "@posthog/quill";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";

const LABELS: Record<string, string> = {
  canvas_add_fragment: "Added a fragment",
  canvas_update_fragment: "Changed a fragment",
  canvas_remove_fragment: "Removed a fragment",
  canvas_set_state: "Set shared state",
  canvas_list_fragments: "Read the board",
  canvas_get_fragment: "Read a fragment",
  canvas_get_state: "Read shared state",
};

/** What a board tool call did, drawn as one line in the conversation. */
export function CanvasV2ToolRow({ toolCall }: ToolViewProps) {
  const tool = canvasV2ToolName(toolCall._meta);
  if (!tool) return null;
  const target = readTarget(toolCall.rawInput);

  return (
    <div className="flex items-center gap-2">
      <Badge variant="default">Board</Badge>
      <Text size="xs" variant="muted">
        {LABELS[tool] ?? tool}
        {target ? `: ${target}` : ""}
      </Text>
    </div>
  );
}

function readTarget(rawInput: unknown): string | null {
  if (typeof rawInput !== "object" || rawInput === null) return null;
  const record = rawInput as Record<string, unknown>;
  const value = record.id ?? record.key;
  return typeof value === "string" ? value : null;
}
