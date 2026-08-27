import type { CanvasMultiSelectOption } from "@posthog/ui/features/canvas/components/canvasFilterSelection";

interface CanvasCreator {
  createdByUuid?: string | null;
  createdBy?: string | null;
}

export function buildCanvasCreatorOptions(
  canvases: readonly CanvasCreator[],
  currentUser?: { uuid: string; name: string },
): CanvasMultiSelectOption[] {
  const creatorsByUuid = new Map<string, string>();
  for (const canvas of canvases) {
    if (
      canvas.createdByUuid &&
      canvas.createdByUuid !== currentUser?.uuid &&
      !creatorsByUuid.has(canvas.createdByUuid)
    ) {
      creatorsByUuid.set(canvas.createdByUuid, canvas.createdBy ?? "Unknown");
    }
  }

  const otherCreators = [...creatorsByUuid.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));

  return [
    ...(currentUser
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
