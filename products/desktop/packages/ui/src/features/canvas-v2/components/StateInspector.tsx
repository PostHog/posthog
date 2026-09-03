import { XIcon } from "@phosphor-icons/react";
import { Button, Heading, Text } from "@posthog/quill";
import {
  STATE_EMPTY,
  STATE_PANEL_CLOSE,
  TOOLBAR_STATE,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { type ReactElement, useMemo } from "react";

export interface StateInspectorProps {
  state: Record<string, unknown>;
  onClose: () => void;
}

/** The board's shared state, read only, one block per key. */
export function StateInspector({
  state,
  onClose,
}: StateInspectorProps): ReactElement {
  const entries = useMemo(
    () =>
      Object.keys(state)
        .sort()
        .map((key) => ({ key, value: formatValue(state[key]) })),
    [state],
  );

  return (
    <div className="@container flex h-full min-h-0 w-full flex-col overflow-hidden border-border border-l">
      <div className="flex items-center justify-between gap-2 border-border border-b px-3 py-2">
        <Heading size="sm">{TOOLBAR_STATE}</Heading>
        <Button
          variant="outline"
          size="icon-xs"
          aria-label={STATE_PANEL_CLOSE}
          onClick={onClose}
        >
          <XIcon size={12} />
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overflow-x-hidden px-3 py-2">
        {entries.length === 0 ? (
          <Text size="sm" variant="muted">
            {STATE_EMPTY}
          </Text>
        ) : null}
        {entries.map((entry) => (
          <div key={entry.key} className="flex min-w-0 flex-col gap-1">
            <Text size="xs" variant="muted" className="break-all">
              {entry.key}
            </Text>
            <pre className="max-h-48 max-w-full overflow-auto rounded border border-border bg-muted p-2 font-mono text-xs">
              {entry.value}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "undefined";
  } catch {
    return "(unserializable)";
  }
}
