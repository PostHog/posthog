import { DotsThreeIcon } from "@phosphor-icons/react";
import type {
  BoardScreenRect,
  ResizeHandle,
} from "@posthog/core/canvas-v2/boardGeometry";
import { RESIZE_HANDLES } from "@posthog/core/canvas-v2/boardGeometry";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { CanvasV2Fragment } from "@posthog/shared";
import {
  BRING_TO_FRONT_ACTION,
  DELETE_FRAGMENT_ACTION,
  DUPLICATE_FRAGMENT_ACTION,
  EDIT_FRAGMENT_ACTION,
  FRAGMENT_MENU_LABEL,
  lastEditedByLabel,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import type { ReactElement } from "react";

export interface FragmentLastEdit {
  name: string;
  /** Already formatted by the caller, which owns the log. */
  when: string;
}

interface FragmentOverlayProps {
  fragment: CanvasV2Fragment;
  /** Pane relative, so the layer can place it with plain CSS offsets. */
  rect: BoardScreenRect;
  selected: boolean;
  highlighted: boolean;
  error?: string;
  lastEditedBy?: FragmentLastEdit;
  onStartMove: (event: React.PointerEvent) => void;
  onStartResize: (handle: ResizeHandle, event: React.PointerEvent) => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onBringToFront: () => void;
  onDelete: () => void;
}

const HANDLE_CLASS: Record<ResizeHandle, string> = {
  nw: "-top-[5px] -left-[5px] cursor-nwse-resize",
  n: "-top-[5px] left-1/2 -translate-x-1/2 cursor-ns-resize",
  ne: "-top-[5px] -right-[5px] cursor-nesw-resize",
  e: "-right-[5px] top-1/2 -translate-y-1/2 cursor-ew-resize",
  se: "-right-[5px] -bottom-[5px] cursor-nwse-resize",
  s: "-bottom-[5px] left-1/2 -translate-x-1/2 cursor-ns-resize",
  sw: "-bottom-[5px] -left-[5px] cursor-nesw-resize",
  w: "-left-[5px] top-1/2 -translate-y-1/2 cursor-ew-resize",
};

/** The chrome of one fragment. Every action is a callback: it holds no state. */
export function FragmentOverlay({
  fragment,
  rect,
  selected,
  highlighted,
  error,
  lastEditedBy,
  onStartMove,
  onStartResize,
  onEdit,
  onDuplicate,
  onBringToFront,
  onDelete,
}: FragmentOverlayProps): ReactElement {
  const label = fragment.title ?? fragment.id;
  const ring = selected
    ? "ring-2 ring-(--accent-9)"
    : highlighted
      ? "ring-2 ring-(--amber-9)"
      : "";
  const chromeVisible = selected || Boolean(error);

  return (
    <div
      className={`pointer-events-none absolute ${ring}`}
      style={{
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      }}
    >
      <div
        className={`-top-6 pointer-events-auto absolute left-0 flex h-6 max-w-full items-center gap-1 rounded-t-(--radius-2) bg-(--gray-3) pr-0.5 pl-1.5 transition-opacity ${
          chromeVisible ? "opacity-100" : "opacity-0 hover:opacity-100"
        }`}
      >
        <button
          type="button"
          className="min-w-0 cursor-grab truncate text-left"
          onPointerDown={onStartMove}
        >
          {lastEditedBy ? (
            <Tooltip>
              <TooltipTrigger render={<span />}>
                <Text size="xs" variant="muted" render={<span />}>
                  {label}
                </Text>
              </TooltipTrigger>
              <TooltipContent side="top">
                {lastEditedByLabel(lastEditedBy.name, lastEditedBy.when)}
              </TooltipContent>
            </Tooltip>
          ) : (
            <Text size="xs" variant="muted" render={<span />}>
              {label}
            </Text>
          )}
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="default"
                size="icon-xs"
                aria-label={FRAGMENT_MENU_LABEL}
              />
            }
          >
            <DotsThreeIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onEdit}>
              {EDIT_FRAGMENT_ACTION}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onDuplicate}>
              {DUPLICATE_FRAGMENT_ACTION}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onBringToFront}>
              {BRING_TO_FRONT_ACTION}
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={onDelete}>
              {DELETE_FRAGMENT_ACTION}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {selected
        ? RESIZE_HANDLES.map((handle) => (
            <div
              key={handle}
              className={`pointer-events-auto absolute h-2.5 w-2.5 rounded-(--radius-1) border border-(--gray-1) bg-(--accent-9) ${HANDLE_CLASS[handle]}`}
              onPointerDown={(event) => onStartResize(handle, event)}
            />
          ))
        : null}

      {error ? (
        <Badge
          variant="destructive"
          className="-bottom-6 pointer-events-auto absolute left-0 max-w-full truncate"
        >
          {error}
        </Badge>
      ) : null}
    </div>
  );
}
