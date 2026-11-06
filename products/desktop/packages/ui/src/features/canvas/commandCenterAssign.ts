import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { getCanvasCellId } from "@posthog/core/command-center/grid";
import {
  placeCanvasInCommandCenter,
  placeTaskInCommandCenter,
} from "@posthog/ui/features/command-center/placeTaskInCommandCenter";

export function commandCenterAssigner(item: ChannelItemModel): () => void {
  return () => {
    if (item.kind === "canvas") {
      placeCanvasInCommandCenter(item.id, item.title);
    } else {
      placeTaskInCommandCenter(item.id, item.title);
    }
  };
}

export function isInCommandCenter(
  item: ChannelItemModel,
  commandCenterCells: readonly (string | null)[],
): boolean {
  return commandCenterCells.some((cell) =>
    item.kind === "canvas"
      ? getCanvasCellId(cell) === item.id
      : cell === item.id,
  );
}
