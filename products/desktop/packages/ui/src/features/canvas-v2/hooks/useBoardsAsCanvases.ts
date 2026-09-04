import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { CanvasV2BoardSummary } from "@posthog/shared";
import {
  useAllCanvasV2Boards,
  useCanvasV2Boards,
} from "@posthog/ui/features/canvas-v2/hooks/useCanvasV2Boards";
import { useCanvasesV2Flag } from "@posthog/ui/features/feature-flags/useCanvasesV2Flag";
import { useMemo } from "react";

const NO_RECORDS: DashboardRecord[] = [];

/** A board, shaped as the canvas record every canvas list already reads. */
export function boardAsCanvas(board: CanvasV2BoardSummary): DashboardRecord {
  return {
    id: board.id,
    channelId: board.channelId,
    name: board.name,
    kind: "freeform",
    description: "",
    templateId: "freeform",
    canvasVersion: 2,
    context: "",
    createdAt: new Date(board.createdAt).getTime(),
    updatedAt: new Date(board.updatedAt).getTime(),
  };
}

/** The boards of one space, ready to list beside its canvases. */
export function useSpaceBoardsAsCanvases(
  channelId: string | undefined,
): DashboardRecord[] {
  const enabled = useCanvasesV2Flag();
  const { boards } = useCanvasV2Boards(enabled ? (channelId ?? "") : "");
  return useMemo(
    () => (enabled && channelId ? boards.map(boardAsCanvas) : NO_RECORDS),
    [boards, channelId, enabled],
  );
}

/** Every board this person can see, ready to list beside their canvases. */
export function useAllBoardsAsCanvases(): DashboardRecord[] {
  const enabled = useCanvasesV2Flag();
  const { boards } = useAllCanvasV2Boards();
  return useMemo(
    () => (enabled ? boards.map(boardAsCanvas) : NO_RECORDS),
    [boards, enabled],
  );
}
