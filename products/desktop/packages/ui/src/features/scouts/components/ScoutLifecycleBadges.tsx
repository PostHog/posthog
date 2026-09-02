import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { deriveScoutLifecycle } from "@posthog/core/scouts/scoutPresentation";
import {
  Badge,
  Text,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";

/**
 * Why a scout is stopped, or about to be. Renders nothing for the healthy
 * states — the enable switch already says whether a scout is on, so the badge
 * only appears when the system did something the user did not ask for.
 */
export function ScoutLifecycleBadge({ config }: { config: ScoutConfig }) {
  const lifecycle = deriveScoutLifecycle(config);
  if (!lifecycle.label) return null;
  return (
    <TooltipProvider delay={300}>
      <Tooltip>
        <TooltipTrigger
          render={
            <Badge
              variant={lifecycle.isSystemPaused ? "destructive" : "warning"}
              className="relative"
            >
              {lifecycle.label}
            </Badge>
          }
        />
        <TooltipContent side="bottom" className="max-w-xs">
          {lifecycle.explanation ?? lifecycle.label}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * The full lifecycle story for surfaces with room for a sentence: what the
 * system did and what gets the scout running again. The fleet list makes do
 * with `ScoutLifecycleBadge`'s tooltip; this is for the scout detail screen.
 */
export function ScoutLifecycleNotice({ config }: { config: ScoutConfig }) {
  const lifecycle = deriveScoutLifecycle(config);
  if (!lifecycle.explanation) return null;
  return (
    <div
      className={`flex flex-wrap items-center gap-2 rounded-(--radius-2) border px-3 py-2 ${
        lifecycle.isSystemPaused
          ? "border-(--red-6) bg-(--red-2)"
          : "border-(--amber-6) bg-(--amber-2)"
      }`}
    >
      <Text
        size="xs"
        className={`leading-snug ${
          lifecycle.isSystemPaused ? "text-(--red-11)" : "text-(--amber-11)"
        }`}
      >
        {lifecycle.explanation}
      </Text>
      {lifecycle.changedAt ? (
        <RelativeTimestamp timestamp={lifecycle.changedAt} />
      ) : null}
    </div>
  );
}
