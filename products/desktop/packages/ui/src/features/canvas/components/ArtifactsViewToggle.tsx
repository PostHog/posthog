import { Kanban, ListIcon, SquaresFourIcon } from "@phosphor-icons/react";
import {
  ToggleGroup,
  ToggleGroupItem,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import {
  ARTIFACTS_VIEW_MODES,
  type ArtifactsViewMode,
  useArtifactsViewStore,
} from "@posthog/ui/features/canvas/stores/artifactsViewStore";
import type { ComponentType } from "react";

const OPTIONS: {
  mode: ArtifactsViewMode;
  label: string;
  Icon: ComponentType<{ size?: number; weight?: "bold" }>;
}[] = [
  { mode: "list", label: "List", Icon: ListIcon },
  { mode: "grid", label: "Grid", Icon: SquaresFourIcon },
  { mode: "masonry", label: "Masonry", Icon: Kanban },
];

function isViewMode(value: string | undefined): value is ArtifactsViewMode {
  return ARTIFACTS_VIEW_MODES.some((mode) => mode === value);
}

// Layout switcher for the artifacts list. A quill ToggleGroup carries the
// pressed state itself, so there's no hand-rolled active styling here.
export function ArtifactsViewToggle({ channelId }: { channelId?: string }) {
  const view = useArtifactsViewStore((s) => s.view);
  const setView = useArtifactsViewStore((s) => s.setView);

  return (
    <TooltipProvider delay={0}>
      <ToggleGroup
        aria-label="Artifacts view"
        value={[view]}
        onValueChange={(next: string[]) => {
          // Pressing the active item would otherwise clear the group — a view
          // is always on, so ignore the empty result.
          const mode = next[0];
          if (isViewMode(mode)) setView(mode, channelId);
        }}
      >
        {OPTIONS.map(({ mode, label, Icon }) => (
          <Tooltip key={mode}>
            <TooltipTrigger
              render={
                <ToggleGroupItem
                  value={mode}
                  size="icon"
                  aria-label={`${label} view`}
                >
                  <Icon size={14} weight="bold" />
                </ToggleGroupItem>
              }
            />
            <TooltipContent side="bottom">{label}</TooltipContent>
          </Tooltip>
        ))}
      </ToggleGroup>
    </TooltipProvider>
  );
}
