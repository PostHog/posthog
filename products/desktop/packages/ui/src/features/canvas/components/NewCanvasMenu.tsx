import { PlusIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { FREEFORM_TEMPLATE_ID } from "@posthog/core/canvas/freeformSchemas";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { trackAndCreateCanvas } from "@posthog/ui/features/canvas/createCanvasAnalytics";
import { useCanvasTemplates } from "@posthog/ui/features/canvas/hooks/useCanvasTemplates";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import {
  DEFAULT_BOARD_NAME,
  NEW_BOARD_TEMPLATE_HINT,
  NEW_BOARD_TEMPLATE_NAME,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { CanvasVersionTag } from "@posthog/ui/features/canvas-v2/components/CanvasVersionTag";
import { useCanvasV2BoardMutations } from "@posthog/ui/features/canvas-v2/hooks/useCanvasV2BoardMutations";
import { useCanvasesV2Flag } from "@posthog/ui/features/feature-flags/useCanvasesV2Flag";
import { navigateToSpaceBoard } from "@posthog/ui/router/navigationBridge";
import type { ReactElement, ReactNode } from "react";

const NEW_CANVAS_ACTION = "New canvas";

/**
 * One kind of canvas the person can start: an icon, a name, and a hint that
 * always stays on one line, so every row in the picker has the same height.
 */
function CanvasKindItem({
  icon,
  name,
  tag,
  hint,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  name: string;
  tag?: ReactNode;
  hint?: string;
  disabled?: boolean;
  onClick: () => void;
}): ReactElement {
  return (
    <DropdownMenuItem
      className="h-auto py-1.5 text-left"
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-1.5 leading-snug">
          <span className="truncate">{name}</span>
          {tag}
        </span>
        {/* quill has no second line for a menu item, so the hint states its own tone. */}
        {hint ? (
          <span className="block truncate text-muted-foreground text-xxs leading-snug">
            {hint}
          </span>
        ) : null}
      </span>
    </DropdownMenuItem>
  );
}

export function NewCanvasMenu({
  channelId,
  variant = "outline",
  compact = false,
}: {
  channelId: string | undefined;
  variant?: "outline" | "primary";
  /** Icon only, for a list header that has no room for the words. */
  compact?: boolean;
}) {
  const templates = useCanvasTemplates();
  const createAndOpen = useCreateAndOpenDashboard(channelId);
  const boardsEnabled = useCanvasesV2Flag();
  const { createBoard, isCreating } = useCanvasV2BoardMutations();
  const { channels } = useChannels();
  // Anything made here must land in a space. Off a space page, that is the
  // person's own space, as a canvas made from the grid does.
  const boardChannelId =
    channelId ??
    channels.find((channel) => channel.channelType === "personal")?.id;

  const trigger = (
    <Button
      variant={variant}
      size={compact ? "icon-sm" : "sm"}
      aria-label={NEW_CANVAS_ACTION}
      className="no-drag"
    >
      <PlusIcon size={14} />
      {compact ? null : NEW_CANVAS_ACTION}
    </Button>
  );

  const newBoard = async (): Promise<void> => {
    if (!boardChannelId) return;
    const board = await createBoard(boardChannelId, DEFAULT_BOARD_NAME);
    navigateToSpaceBoard(boardChannelId, board.id);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={trigger} />
      <DropdownMenuContent align="end" className="w-72">
        {boardsEnabled && boardChannelId ? (
          <CanvasKindItem
            disabled={isCreating}
            hint={NEW_BOARD_TEMPLATE_HINT}
            icon={<SquaresFourIcon size={14} className="text-gray-9" />}
            name={NEW_BOARD_TEMPLATE_NAME}
            onClick={newBoard}
            tag={<CanvasVersionTag />}
          />
        ) : null}
        {templates.length === 0 ? (
          <CanvasKindItem
            icon={iconForTemplate(FREEFORM_TEMPLATE_ID, { size: 14 })}
            name={NEW_CANVAS_ACTION}
            onClick={() =>
              trackAndCreateCanvas(
                channelId,
                undefined,
                "dashboards_grid",
                () => void createAndOpen({ channelId: boardChannelId }),
              )
            }
          />
        ) : (
          templates.map((template) => (
            <CanvasKindItem
              hint={template.description}
              icon={iconForTemplate(template.id, { size: 14 })}
              key={template.id}
              name={template.name}
              onClick={() =>
                trackAndCreateCanvas(
                  channelId,
                  template.id,
                  "dashboards_grid",
                  () =>
                    void createAndOpen({
                      templateId: template.id,
                      channelId: boardChannelId,
                    }),
                )
              }
            />
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
