import type { PiQueueSnapshot } from "@posthog/core/pi-runtime/piSessionController";
import { QueuedMessageView } from "@posthog/ui/features/sessions/components/session-update/QueuedMessageView";

interface PiQueuedMessagesDockProps {
  queue: PiQueueSnapshot;
  onEdit(): void;
  onRemove(): void;
}

export function PiQueuedMessagesDock({
  queue,
  onEdit,
  onRemove,
}: PiQueuedMessagesDockProps) {
  const messages = [...queue.steering, ...queue.followUp];
  const content = messages.join("\n\n");
  if (!content) {
    return null;
  }

  return (
    <div className="mb-1">
      <QueuedMessageView
        message={{
          id: "pi-queued-message",
          content,
          queuedAt: 0,
        }}
        onEdit={onEdit}
        onRemove={messages.length === 1 ? onRemove : undefined}
      />
    </div>
  );
}
