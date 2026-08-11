import type { PiExtensionWidget } from "@posthog/core/pi-runtime/piExtensionStore";

interface PiExtensionWidgetsProps {
  widgets: Record<string, PiExtensionWidget>;
  placement: PiExtensionWidget["placement"];
}

export function PiExtensionWidgets({
  widgets,
  placement,
}: PiExtensionWidgetsProps) {
  const visible = Object.entries(widgets).filter(
    ([, widget]) => widget.placement === placement,
  );
  if (visible.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-1 py-1">
      {visible.map(([key, widget]) => (
        <div
          key={key}
          className="rounded-md border border-border bg-muted/40 px-2 py-1 font-mono text-muted-foreground text-xs"
        >
          <div className="whitespace-pre-wrap">
            {widget.lines.join("\n") || " "}
          </div>
        </div>
      ))}
    </div>
  );
}

export function PiExtensionStatuses({
  statuses,
}: {
  statuses: Record<string, string>;
}) {
  const visible = Object.entries(statuses);
  if (visible.length === 0) {
    return null;
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: Keep the explicit live-region role requested for dynamic session status updates.
    <div
      aria-live="polite"
      role="status"
      className="flex flex-wrap gap-x-3 gap-y-1 px-1 py-1 text-muted-foreground text-xs"
    >
      {visible.map(([key, text]) => (
        <span key={key}>{text}</span>
      ))}
    </div>
  );
}
