import type { BoardSyncStatus } from "@posthog/core/canvas-v2/boardSync";
import { Dot, Text } from "@posthog/quill";
import type { ReactElement } from "react";

export interface SyncChipProps {
  status: BoardSyncStatus;
}

type DotVariant = "default" | "success" | "warning" | "destructive";

const STATUS_LOOK: Record<
  BoardSyncStatus,
  { label: string; dot: DotVariant; pulse: boolean; destructive: boolean }
> = {
  loading: {
    label: "Loading…",
    dot: "default",
    pulse: true,
    destructive: false,
  },
  synced: {
    label: "Synced",
    dot: "success",
    pulse: false,
    destructive: false,
  },
  saving: {
    label: "Saving…",
    dot: "default",
    pulse: true,
    destructive: false,
  },
  offline: {
    label: "Offline. Changes are saved when you reconnect.",
    dot: "warning",
    pulse: false,
    destructive: false,
  },
  error: {
    label: "Could not sync the board",
    dot: "destructive",
    pulse: false,
    destructive: true,
  },
};

/** The sync state of the open board. Who else is here shows as faces. */
export function SyncChip({ status }: SyncChipProps): ReactElement {
  const look = STATUS_LOOK[status];

  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Dot variant={look.dot} pulse={look.pulse} />
      <Text
        size="xs"
        variant={look.destructive ? "destructive" : "muted"}
        className="truncate"
      >
        {look.label}
      </Text>
    </div>
  );
}
