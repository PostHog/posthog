import { DotsThreeIcon } from "@phosphor-icons/react";
import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { useState } from "react";
import type { PlacementActions } from "./placementActions";

/**
 * Actions for one grid card, rendered only while the canvas is editable. The
 * menu stays in the card's outer chrome so it is available for live component
 * frames as well as pending and generating cards.
 */
export function GridPlacementMenu({
  placement,
  patching,
  actions,
}: {
  placement: GridPlacement;
  patching: boolean;
  actions: PlacementActions;
}) {
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const hasConversation = !!placement.generationTaskId;

  const confirmDelete = () => {
    setConfirmDeleteOpen(false);
    actions.remove(placement);
  };

  return (
    <div
      // An open menu keeps its trigger visible after the pointer leaves the
      // card, which the trigger already states as data-popup-open.
      className="absolute top-1 right-1 z-20 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 has-[[data-popup-open]]:opacity-100"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="outline" size="icon-sm" aria-label="Card options">
              <DotsThreeIcon size={16} weight="bold" />
            </Button>
          }
        />
        <DropdownMenuContent align="end" side="bottom" sideOffset={4}>
          {hasConversation ? (
            <>
              <DropdownMenuItem onClick={() => actions.discuss(placement)}>
                {placement.status === "generating"
                  ? "View progress"
                  : "View conversation"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          ) : null}
          <DropdownMenuItem
            variant="destructive"
            disabled={patching}
            onClick={() => setConfirmDeleteOpen(true)}
          >
            Delete…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete card?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the card from the canvas.
              {placement.component ? " The reusable component stays." : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button
              variant="destructive"
              size="sm"
              disabled={patching}
              onClick={confirmDelete}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
