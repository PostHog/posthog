import type { CanvasMultiSelectOption } from "@posthog/ui/features/canvas/components/canvasFilterSelection";

interface CanvasCreator {
  channelId: string;
  createdByUuid?: string | null;
  createdBy?: string | null;
}

export function buildCanvasCreatorOptions(
  canvases: readonly CanvasCreator[],
  currentUser?: { uuid: string; name: string },
  spaceIds: readonly string[] = [],
): CanvasMultiSelectOption[] {
  const selectedSpaceIds = new Set(spaceIds);
  const limitsCreatorsBySpace = selectedSpaceIds.size > 0;
  const creatorsByUuid = new Map<string, string>();
  let currentUserHasCanvas = false;
  for (const canvas of canvases) {
    if (limitsCreatorsBySpace && !selectedSpaceIds.has(canvas.channelId)) {
      continue;
    }
    if (canvas.createdByUuid === currentUser?.uuid) {
      currentUserHasCanvas = true;
      continue;
    }
    if (canvas.createdByUuid && !creatorsByUuid.has(canvas.createdByUuid)) {
      creatorsByUuid.set(canvas.createdByUuid, canvas.createdBy ?? "Unknown");
    }
  }

  const otherCreators = [...creatorsByUuid.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));

  return [
    ...(currentUser && (!limitsCreatorsBySpace || currentUserHasCanvas)
      ? [
          {
            value: currentUser.uuid,
            label: "Me",
            searchLabel: currentUser.name,
          },
        ]
      : []),
    { value: null, label: "Anyone" },
    ...otherCreators,
  ];
}
