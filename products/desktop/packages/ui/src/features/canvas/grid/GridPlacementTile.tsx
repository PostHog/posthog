import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Input,
  Spinner,
  Text,
} from "@posthog/quill";
import { taskCardNavigation } from "@posthog/ui/features/canvas/taskCardNavigation";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { ComponentFrame } from "./ComponentFrame";
import { useComponentStore } from "./useGridLayout";

export interface PlacementTileActions {
  /** Dispatch an agent task to fill this placement with the given ask. */
  describe: (placement: GridPlacement, prompt: string) => void;
  /** Fill this placement with an existing store component. */
  place: (placement: GridPlacement, component: DashboardRecord) => void;
  /** Remove this placement from the layout. */
  remove: (placement: GridPlacement) => void;
}

/**
 * One placement on the grid, rendered by lifecycle status: a live widget, a
 * drawn box awaiting its description, an agent filling it, or a failed fill
 * offering a retry.
 */
export function GridPlacementTile({
  placement,
  channelId,
  interactive,
  actions,
}: {
  placement: GridPlacement;
  channelId: string;
  interactive: boolean;
  actions: PlacementTileActions;
}) {
  if (placement.status === "live" && placement.component) {
    return <ComponentFrame placement={placement} />;
  }
  if (placement.status === "generating") {
    return (
      <GeneratingTile
        placement={placement}
        channelId={channelId}
        interactive={interactive}
        actions={actions}
      />
    );
  }
  return (
    <DescribeTile
      placement={placement}
      failed={placement.status === "failed"}
      interactive={interactive}
      actions={actions}
    />
  );
}

function GeneratingTile({
  placement,
  channelId,
  interactive,
  actions,
}: {
  placement: GridPlacement;
  channelId: string;
  interactive: boolean;
  actions: PlacementTileActions;
}) {
  const navigate = useNavigate();
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
      <Spinner />
      <Text size="sm" className="line-clamp-2">
        {placement.prompt ?? "Building this widget…"}
      </Text>
      <div className="flex items-center gap-1">
        {placement.generationTaskId ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              navigate(
                taskCardNavigation(
                  channelId,
                  placement.generationTaskId as string,
                ),
              )
            }
          >
            View progress
          </Button>
        ) : null}
        {interactive ? (
          <Button
            variant="default"
            size="sm"
            onClick={() => actions.remove(placement)}
          >
            Remove
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function DescribeTile({
  placement,
  failed,
  interactive,
  actions,
}: {
  placement: GridPlacement;
  failed: boolean;
  interactive: boolean;
  actions: PlacementTileActions;
}) {
  const [prompt, setPrompt] = useState(placement.prompt ?? "");
  const [storeOpen, setStoreOpen] = useState(false);
  const [storeSearch, setStoreSearch] = useState("");
  // The store query only fires once the picker opens — a grid full of drawn
  // boxes must not fan out one store fetch per tile on mount.
  const { components } = useComponentStore(storeSearch, { enabled: storeOpen });
  const placeable = components.filter(
    (component) => component.componentMeta && component.publishedBuildId,
  );

  if (!interactive) {
    return (
      <div className="flex h-full w-full items-center justify-center p-3">
        <Text size="sm">
          {failed ? "This widget failed to build." : "An empty widget."}
        </Text>
      </div>
    );
  }
  const submit = () => {
    if (prompt.trim()) actions.describe(placement, prompt.trim());
  };
  return (
    <div className="flex h-full w-full flex-col justify-center gap-2 p-3">
      {failed ? (
        <Text size="sm">This widget failed to build. Describe it again:</Text>
      ) : null}
      <form
        className="flex items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Input
          autoFocus
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="What should go here?"
        />
        <Button type="submit" size="sm" disabled={!prompt.trim()}>
          {failed ? "Retry" : "Create"}
        </Button>
      </form>
      <div className="flex items-center gap-1">
        <DropdownMenu open={storeOpen} onOpenChange={setStoreOpen}>
          <DropdownMenuTrigger
            render={
              <Button variant="outline" size="sm">
                Choose from store…
              </Button>
            }
          />
          <DropdownMenuContent align="start">
            <div className="p-1">
              <Input
                value={storeSearch}
                onChange={(event) => setStoreSearch(event.target.value)}
                placeholder="Search components"
              />
            </div>
            {placeable.length === 0 ? (
              <DropdownMenuItem disabled>No components yet</DropdownMenuItem>
            ) : (
              placeable.map((component) => (
                <DropdownMenuItem
                  key={component.id}
                  onClick={() => actions.place(placement, component)}
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate">{component.name}</span>
                    {component.description ? (
                      <span className="truncate text-xs opacity-70">
                        {component.description}
                      </span>
                    ) : null}
                  </div>
                </DropdownMenuItem>
              ))
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          variant="default"
          size="sm"
          onClick={() => actions.remove(placement)}
        >
          Remove
        </Button>
      </div>
    </div>
  );
}
