import { DotsThreeIcon } from "@phosphor-icons/react";
import type {
  BoardScreenRect,
  ResizeHandle,
} from "@posthog/core/canvas-v2/boardGeometry";
import { RESIZE_HANDLES } from "@posthog/core/canvas-v2/boardGeometry";
import {
  Badge,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { CanvasV2Fragment } from "@posthog/shared";
import {
  BRING_TO_FRONT_ACTION,
  bringFragmentsToFrontAction,
  DELETE_FRAGMENT_ACTION,
  DUPLICATE_FRAGMENT_ACTION,
  deleteFragmentsAction,
  duplicateFragmentsAction,
  EDIT_FRAGMENT_ACTION,
  FRAGMENT_ERROR_BADGE,
  FRAGMENT_MENU_LABEL,
  FULL_SCREEN_FRAGMENT_ACTION,
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
  /** Resize handles only fit one fragment, so the layer decides. */
  resizable: boolean;
  /** How many fragments a group action from this menu changes. */
  selectionCount: number;
  highlighted: boolean;
  error?: string;
  lastEditedBy?: FragmentLastEdit;
  onStartMove: (event: React.PointerEvent) => void;
  onStartResize: (handle: ResizeHandle, event: React.PointerEvent) => void;
  onEdit: () => void;
  onFocus: () => void;
  onDuplicate: () => void;
  onBringToFront: () => void;
  onDelete: () => void;
}

const CORNER_HANDLES = [
  "nw",
  "ne",
  "se",
  "sw",
] as const satisfies readonly ResizeHandle[];

const HANDLE_CLASS: Record<ResizeHandle, string> = {
  nw: "-top-[7px] -left-[7px] cursor-nwse-resize",
  n: "-top-[7px] left-1/2 -translate-x-1/2 cursor-ns-resize",
  ne: "-top-[7px] -right-[7px] cursor-nesw-resize",
  e: "-right-[7px] top-1/2 -translate-y-1/2 cursor-ew-resize",
  se: "-right-[7px] -bottom-[7px] cursor-nwse-resize",
  s: "-bottom-[7px] left-1/2 -translate-x-1/2 cursor-ns-resize",
  sw: "-bottom-[7px] -left-[7px] cursor-nesw-resize",
  w: "-left-[7px] top-1/2 -translate-y-1/2 cursor-ew-resize",
};

function CornerBrackets(): ReactElement {
  return (
    <>
      {CORNER_HANDLES.map((corner) => (
        <span
          key={corner}
          className={`pointer-events-none absolute size-3 border-(--gray-9) ${BRACKET_CLASS[corner]}`}
        />
      ))}
    </>
  );
}

const BRACKET_CLASS: Record<(typeof CORNER_HANDLES)[number], string> = {
  nw: "-top-[3px] -left-[3px] rounded-tl-[6px] border-t-[1.5px] border-l-[1.5px]",
  ne: "-top-[3px] -right-[3px] rounded-tr-[6px] border-t-[1.5px] border-r-[1.5px]",
  se: "-right-[3px] -bottom-[3px] rounded-br-[6px] border-r-[1.5px] border-b-[1.5px]",
  sw: "-bottom-[3px] -left-[3px] rounded-bl-[6px] border-b-[1.5px] border-l-[1.5px]",
};

function handlesFor(fragment: CanvasV2Fragment): readonly ResizeHandle[] {
  if (fragment.w >= 200 && fragment.h >= 120) return RESIZE_HANDLES;
  return CORNER_HANDLES;
}

function nameTagClass(outlined: boolean, amber: boolean): string {
  if (!outlined) return "text-(--gray-11)";
  return amber ? "text-(--amber-11)" : "text-(--accent-11)";
}

/** The chrome of one fragment. Every action is a callback: it holds no state. */
export function FragmentOverlay({
  fragment,
  rect,
  selected,
  resizable,
  selectionCount,
  highlighted,
  error,
  lastEditedBy,
  onStartMove,
  onStartResize,
  onEdit,
  onFocus,
  onDuplicate,
  onBringToFront,
  onDelete,
}: FragmentOverlayProps): ReactElement {
  const label = fragment.title ?? fragment.id;
  const amber = highlighted && !selected;
  const outlined = selected || highlighted;
  const chromeVisible = selected || highlighted || Boolean(error);
  const isGroup = selectionCount > 1;

  return (
    <div
      className="pointer-events-none absolute"
      style={{
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      }}
    >
      {highlighted ? (
        <div
          className="-inset-[3px] pointer-events-none absolute rounded-[13px]"
          style={{ boxShadow: "0 0 0 3px var(--amber-a7)" }}
        />
      ) : null}
      {selected && !resizable ? <CornerBrackets /> : null}
      <div
        className={`-top-[22px] pointer-events-auto absolute left-0 flex h-[20px] max-w-full items-center gap-0.5 rounded-(--radius-2) py-0 pr-0.5 pl-0.5 transition-opacity duration-150 ${nameTagClass(
          outlined,
          amber,
        )} ${chromeVisible ? "opacity-100" : "opacity-0 hover:opacity-100"}`}
      >
        <button
          type="button"
          className="min-w-0 cursor-grab truncate text-left font-medium text-[11px] leading-none tracking-[0.005em]"
          onPointerDown={onStartMove}
        >
          {lastEditedBy ? (
            <Tooltip>
              <TooltipTrigger render={<span className="truncate" />}>
                {label}
              </TooltipTrigger>
              <TooltipContent side="top">
                {lastEditedByLabel(lastEditedBy.name, lastEditedBy.when)}
              </TooltipContent>
            </Tooltip>
          ) : (
            label
          )}
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button
                type="button"
                aria-label={FRAGMENT_MENU_LABEL}
                className="flex size-[18px] shrink-0 items-center justify-center rounded-(--radius-1) transition-colors hover:bg-(--gray-a4)"
              />
            }
          >
            <DotsThreeIcon weight="bold" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {isGroup ? null : (
              <DropdownMenuItem onClick={onFocus}>
                {FULL_SCREEN_FRAGMENT_ACTION}
              </DropdownMenuItem>
            )}
            {isGroup ? null : (
              <DropdownMenuItem onClick={onEdit}>
                {EDIT_FRAGMENT_ACTION}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={onDuplicate}>
              {isGroup
                ? duplicateFragmentsAction(selectionCount)
                : DUPLICATE_FRAGMENT_ACTION}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onBringToFront}>
              {isGroup
                ? bringFragmentsToFrontAction(selectionCount)
                : BRING_TO_FRONT_ACTION}
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={onDelete}>
              {isGroup
                ? deleteFragmentsAction(selectionCount)
                : DELETE_FRAGMENT_ACTION}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {resizable
        ? handlesFor(fragment).map((handle) => (
            <div
              key={handle}
              className={`pointer-events-auto absolute size-[9px] rounded-full border-(--accent-9) border-[1.5px] bg-(--gray-1) shadow-xs transition-transform hover:scale-125 ${HANDLE_CLASS[handle]}`}
              onPointerDown={(event) => onStartResize(handle, event)}
            />
          ))
        : null}

      {error ? (
        <Badge
          variant="destructive"
          title={error}
          className="-bottom-[22px] pointer-events-auto absolute left-0 h-[18px] px-1.5 text-[10px]"
        >
          {FRAGMENT_ERROR_BADGE}
        </Badge>
      ) : null}
    </div>
  );
}
