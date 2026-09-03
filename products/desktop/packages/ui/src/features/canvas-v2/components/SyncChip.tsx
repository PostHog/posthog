import type { BoardSyncStatus } from "@posthog/core/canvas-v2/boardSync";
import { Dot, Text } from "@posthog/quill";
import {
  SYNC_ERROR,
  SYNC_LOADING,
  SYNC_OFFLINE,
  SYNC_SAVING,
  SYNC_SYNCED,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
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
    label: SYNC_LOADING,
    dot: "default",
    pulse: true,
    destructive: false,
  },
  synced: {
    label: SYNC_SYNCED,
    dot: "success",
    pulse: false,
    destructive: false,
  },
  saving: {
    label: SYNC_SAVING,
    dot: "default",
    pulse: true,
    destructive: false,
  },
  offline: {
    label: SYNC_OFFLINE,
    dot: "warning",
    pulse: false,
    destructive: false,
  },
  error: {
    label: SYNC_ERROR,
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
