import {
  ArrowsOutIcon,
  BracketsCurlyIcon,
  ChatCircleIcon,
  ClockCounterClockwiseIcon,
  MagnifyingGlassMinusIcon,
  MagnifyingGlassPlusIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Toggle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import {
  TOOLBAR_CHAT,
  TOOLBAR_FIT_TO_CONTENT,
  TOOLBAR_HISTORY,
  TOOLBAR_LIBRARY,
  TOOLBAR_STATE,
  TOOLBAR_ZOOM_IN,
  TOOLBAR_ZOOM_OUT,
  TOOLBAR_ZOOM_RESET,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import type { ReactElement, ReactNode } from "react";

interface BoardToolbarProps {
  zoom: number;
  paletteOpen: boolean;
  chatOpen: boolean;
  historyOpen: boolean;
  inspectorOpen: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
  onFitToContent: () => void;
  onTogglePalette: () => void;
  onToggleChat: () => void;
  onToggleHistory: () => void;
  onToggleInspector: () => void;
  /** The sync chip, owned by the caller because it reads the sync state. */
  syncChip?: ReactNode;
}

export function BoardToolbar({
  zoom,
  paletteOpen,
  chatOpen,
  historyOpen,
  inspectorOpen,
  onZoomIn,
  onZoomOut,
  onZoomReset,
  onFitToContent,
  onTogglePalette,
  onToggleChat,
  onToggleHistory,
  onToggleInspector,
  syncChip,
}: BoardToolbarProps): ReactElement {
  return (
    <TooltipProvider delay={400}>
      <div className="flex items-center gap-1 border-(--gray-4) border-b px-2 py-1">
        <IconAction label={TOOLBAR_ZOOM_OUT} onClick={onZoomOut}>
          <MagnifyingGlassMinusIcon />
        </IconAction>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button variant="default" size="xs" onClick={onZoomReset}>
                {`${Math.round(zoom * 100)}%`}
              </Button>
            }
          />
          <TooltipContent side="bottom">{TOOLBAR_ZOOM_RESET}</TooltipContent>
        </Tooltip>
        <IconAction label={TOOLBAR_ZOOM_IN} onClick={onZoomIn}>
          <MagnifyingGlassPlusIcon />
        </IconAction>
        <IconAction label={TOOLBAR_FIT_TO_CONTENT} onClick={onFitToContent}>
          <ArrowsOutIcon />
        </IconAction>

        <div className="mx-1 h-5 w-px bg-(--gray-4)" />

        <IconToggle
          label={TOOLBAR_LIBRARY}
          pressed={paletteOpen}
          onPressedChange={onTogglePalette}
        >
          <SquaresFourIcon />
        </IconToggle>
        <IconToggle
          label={TOOLBAR_CHAT}
          pressed={chatOpen}
          onPressedChange={onToggleChat}
        >
          <ChatCircleIcon />
        </IconToggle>
        <IconToggle
          label={TOOLBAR_HISTORY}
          pressed={historyOpen}
          onPressedChange={onToggleHistory}
        >
          <ClockCounterClockwiseIcon />
        </IconToggle>
        <IconToggle
          label={TOOLBAR_STATE}
          pressed={inspectorOpen}
          onPressedChange={onToggleInspector}
        >
          <BracketsCurlyIcon />
        </IconToggle>

        <div className="ml-auto flex items-center gap-2">{syncChip}</div>
      </div>
    </TooltipProvider>
  );
}

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}): ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            onClick={onClick}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

function IconToggle({
  label,
  pressed,
  onPressedChange,
  children,
}: {
  label: string;
  pressed: boolean;
  onPressedChange: () => void;
  children: ReactNode;
}): ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Toggle
            size="sm"
            aria-label={label}
            pressed={pressed}
            onPressedChange={onPressedChange}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}
