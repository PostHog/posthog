import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import {
  openRightPanelSide,
  SIDE_ORDER,
  SIDES,
} from "@posthog/ui/features/navigation/rightPanelSide";
import type { RightPanelSide } from "@posthog/ui/features/navigation/rightPanelStore";
import { TIP_KEYS } from "@posthog/ui/features/settings/tipKeys";
import { TeachingTip } from "@posthog/ui/primitives/TeachingTip";

/** The one lesson this switcher teaches: where a run's deliverables land. */
const ARTIFACTS_PANEL_TIP = TIP_KEYS.sessionArtifactsLocation;

/** One side's button: opens that panel, or closes it when it is the one open. */
function SideButton({
  side,
  active,
  taskId,
  marked = false,
}: {
  side: RightPanelSide;
  active: RightPanelSide | null;
  taskId: string;
  /** Something has arrived on this side that the panel hasn't shown yet. */
  marked?: boolean;
}) {
  const { label, Icon } = SIDES[side];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={marked ? `${label} (new)` : label}
            data-selected={active === side || undefined}
            onClick={() =>
              openRightPanelSide(active === side ? null : side, taskId)
            }
            className="relative text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            <Icon size={16} />
            {marked && (
              // Ringed so the dot reads where it overlaps the icon's strokes.
              <span
                aria-hidden
                className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-primary ring-2 ring-background"
              />
            )}
          </Button>
        }
      />
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * One button per side, the active one toggling the panel closed. Pinned to the
 * row's top right, so the panel comes and goes underneath it.
 */
export function RightPanelButtons({
  active,
  taskId,
  hasNewArtifacts,
  offerArtifactsTip = false,
  artifactCount,
}: {
  active: RightPanelSide | null;
  taskId: string;
  /** Artifacts have arrived that this session's panel hasn't shown yet. */
  hasNewArtifacts: boolean;
  /** The turn that produced them has ended, so the tip can point at where they went. */
  offerArtifactsTip?: boolean;
  /** How many the session has, so each new one is a fresh chance to teach. */
  artifactCount?: number;
}) {
  return (
    <TooltipProvider delay={400}>
      <div className="pointer-events-auto flex shrink-0 items-center gap-0.5">
        {SIDE_ORDER.map((side) =>
          side === "artifacts" ? (
            <TeachingTip
              key={side}
              id={ARTIFACTS_PANEL_TIP}
              open={offerArtifactsTip}
              // `open` can hold across runs; the count is what separates them.
              moment={artifactCount}
              message="New artifacts show up here"
            >
              <SideButton
                side={side}
                active={active}
                taskId={taskId}
                marked={hasNewArtifacts}
              />
            </TeachingTip>
          ) : (
            <SideButton
              key={side}
              side={side}
              active={active}
              taskId={taskId}
            />
          ),
        )}
      </div>
    </TooltipProvider>
  );
}
