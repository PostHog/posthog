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
import { useSketchpadsFlag } from "@posthog/ui/features/feature-flags/useSketchpadsFlag";
import { useSketchpadMutations } from "@posthog/ui/features/sketchpad/hooks/useSketchpadMutations";
import {
  DEFAULT_SKETCHPAD_NAME,
  NEW_SKETCHPAD_TEMPLATE_HINT,
  NEW_SKETCHPAD_TEMPLATE_NAME,
} from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { navigateToSpaceSketchpad } from "@posthog/ui/router/navigationBridge";
import type { ReactElement, ReactNode } from "react";

const NEW_CANVAS_ACTION = "New canvas";

function CanvasKindItem({
  icon,
  name,
  hint,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  name: string;
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
        </span>
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
  compact?: boolean;
}) {
  const templates = useCanvasTemplates();
  const createAndOpen = useCreateAndOpenDashboard(channelId);
  const sketchpadsEnabled = useSketchpadsFlag();
  const { createSketchpad, isCreating } = useSketchpadMutations();
  const { channels } = useChannels();
  const sketchpadChannelId =
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

  const newSketchpad = async (): Promise<void> => {
    if (!sketchpadChannelId) return;
    const board = await createSketchpad(
      sketchpadChannelId,
      DEFAULT_SKETCHPAD_NAME,
    );
    navigateToSpaceSketchpad(sketchpadChannelId, board.id);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={trigger} />
      <DropdownMenuContent align="end" className="w-72">
        {sketchpadsEnabled && sketchpadChannelId ? (
          <CanvasKindItem
            disabled={isCreating}
            hint={NEW_SKETCHPAD_TEMPLATE_HINT}
            icon={<SquaresFourIcon size={14} className="text-gray-9" />}
            name={NEW_SKETCHPAD_TEMPLATE_NAME}
            onClick={newSketchpad}
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
                () => void createAndOpen({ channelId: sketchpadChannelId }),
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
                      channelId: sketchpadChannelId,
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
