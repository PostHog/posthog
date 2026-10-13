import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";

/** What a card's chrome and its tile can do to one placement. */
export interface PlacementActions {
  /** Dispatch an agent task to fill this placement with the given ask. */
  describe: (placement: GridPlacement, prompt: string) => Promise<void>;
  /** Put a stalled placement back to pending so it can be re-described. */
  reset: (placement: GridPlacement) => void;
  /** Remove this placement from the layout. */
  remove: (placement: GridPlacement) => void;
  /** Open this placement's task conversation in the canvas's side panel. */
  discuss: (placement: GridPlacement) => void;
}
