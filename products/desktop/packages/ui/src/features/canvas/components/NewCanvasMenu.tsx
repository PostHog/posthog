import { PlusIcon } from "@phosphor-icons/react";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import {
  type CreateSurface,
  trackAndCreateCanvas,
} from "@posthog/ui/features/canvas/createCanvasAnalytics";
import { useCanvasTemplates } from "@posthog/ui/features/canvas/hooks/useCanvasTemplates";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useState } from "react";

// The list of template options shared by the canvas-create surfaces (the
// dashboards-grid dialog and the sidebar "+" dropdown). Picking a template
// creates + opens the canvas, then calls `onPicked` (e.g. to close the
// surrounding dialog). Renders nothing until templates load.
export function CanvasTemplateList({
  channelId,
  surface,
  onPicked,
}: {
  channelId: string | undefined;
  surface: CreateSurface;
  onPicked?: () => void;
}) {
  const templates = useCanvasTemplates();
  const createAndOpen = useCreateAndOpenDashboard(channelId);

  return (
    <div className="flex flex-col gap-2">
      {templates.map((t) => (
        <Button
          key={t.id}
          variant="default"
          className="h-auto w-full flex-col items-start gap-0.5 whitespace-normal py-3 text-left"
          onClick={() => {
            onPicked?.();
            trackAndCreateCanvas(
              channelId,
              t.id,
              surface,
              () => void createAndOpen({ templateId: t.id }),
            );
          }}
        >
          <span className="font-medium">{t.name}</span>
          <span className="font-normal text-muted-foreground/80 text-xs [text-wrap:initial]">
            {t.description}
          </span>
        </Button>
      ))}
    </div>
  );
}

// Controlled template picker: lists canvas templates; choosing one creates +
// opens the canvas. Carries no trigger of its own so callers (the dashboards
// grid button, the sidebar "+" dropdown) can open it from wherever.
export function NewCanvasDialog({
  channelId,
  surface,
  open,
  onOpenChange,
}: {
  channelId: string | undefined;
  surface: CreateSurface;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Choose a template</DialogTitle>
          <DialogDescription>
            This gives the agent context for which guardrails to follow when
            generating UI.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="[&_*[data-slot=scroll-area-viewport]]:px-2 [&_*[data-slot=scroll-area-viewport]]:py-px">
          <CanvasTemplateList
            channelId={channelId}
            surface={surface}
            onPicked={() => onOpenChange(false)}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

// "New canvas" entry point: a button that opens the template picker. Falls back
// to a plain create (default template) until templates load.
export function NewCanvasMenu({
  channelId,
  variant = "outline",
}: {
  channelId: string | undefined;
  variant?: "outline" | "primary";
}) {
  const [open, setOpen] = useState(false);
  const templates = useCanvasTemplates();
  const createAndOpen = useCreateAndOpenDashboard(channelId);

  if (templates.length === 0) {
    return (
      <Button
        variant={variant}
        size="sm"
        className="no-drag"
        onClick={() =>
          trackAndCreateCanvas(
            channelId,
            undefined,
            "dashboards_grid",
            () => void createAndOpen(),
          )
        }
      >
        <PlusIcon size={14} />
        New canvas
      </Button>
    );
  }

  return (
    <>
      <Button
        variant={variant}
        size="sm"
        className="no-drag"
        onClick={() => setOpen(true)}
      >
        <PlusIcon size={14} />
        New canvas
      </Button>
      <NewCanvasDialog
        channelId={channelId}
        surface="dashboards_grid"
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
