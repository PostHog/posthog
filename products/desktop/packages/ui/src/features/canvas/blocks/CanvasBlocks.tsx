import { ChartLineUp, type Icon, SquaresFour } from "@phosphor-icons/react";
import {
  CANVAS_STARTERS,
  type CanvasStarter,
} from "@posthog/core/canvas/blockLibrary/blockProject";
import { isPlaceholderCanvasName } from "@posthog/core/canvas/canvasNaming";
import {
  useCanvasSourceAutosave,
  useStartCanvasFromStarter,
} from "@posthog/ui/features/canvas/blocks/canvasSourceHooks";
import {
  useDashboard,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useDashboardEditStore } from "@posthog/ui/features/canvas/stores/dashboardEditStore";

const STARTER_LOOKS: Record<string, { icon: Icon; color: string }> = {
  blank: { icon: SquaresFour, color: "blue" },
  "product-overview": { icon: ChartLineUp, color: "orange" },
};

const NAMED_STARTERS = new Set(["product-overview"]);

export function CanvasSourceAutosave({ canvasId }: { canvasId: string }) {
  useCanvasSourceAutosave(canvasId);
  return null;
}

export function CanvasBlocksStarter({ canvasId }: { canvasId: string }) {
  const start = useStartCanvasFromStarter(canvasId);
  const setTab = useCanvasChatPanelStore((state) => state.setTab);
  const setEditing = useDashboardEditStore((state) => state.setEditing);
  const { dashboard } = useDashboard(canvasId);
  const { renameDashboard } = useDashboardMutations();

  const pick = (starter: CanvasStarter) => {
    setTab("blocks");
    setEditing(canvasId, true);
    start(starter);
    if (!NAMED_STARTERS.has(starter.id)) return;
    if (!dashboard || !isPlaceholderCanvasName(dashboard.name)) return;
    void renameDashboard(canvasId, starter.name).catch(() => undefined);
  };

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {CANVAS_STARTERS.map((starter) => {
        const look = STARTER_LOOKS[starter.id] ?? {
          icon: SquaresFour,
          color: "blue",
        };
        const StarterIcon = look.icon;
        return (
          <button
            key={starter.id}
            type="button"
            onClick={() => pick(starter)}
            className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-(--gray-a3) bg-(--color-panel-solid) px-2.5 py-2 text-left shadow-[0_1px_3px_rgba(0,0,0,0.04),0_1px_2px_rgba(0,0,0,0.02)] transition-[border-color,box-shadow] hover:border-(--card-hover-border) hover:shadow-[0_2px_8px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)]"
            style={
              {
                "--card-hover-border": `var(--${look.color}-6)`,
              } as React.CSSProperties
            }
          >
            <span
              className="flex size-6 shrink-0 items-center justify-center rounded-md"
              style={{ backgroundColor: `var(--${look.color}-3)` }}
            >
              <StarterIcon
                size={14}
                weight="duotone"
                color={`var(--${look.color}-9)`}
              />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="min-w-0 truncate font-medium text-foreground text-xs">
                {starter.name}
              </span>
              <span className="line-clamp-1 text-muted-foreground text-xs leading-normal">
                {starter.description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
