import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import type { ScoutDetailTab } from "@posthog/core/scouts/scoutDetailTabs";
import {
  deriveScoutLifecycle,
  scoutHealthNotice,
} from "@posthog/core/scouts/scoutPresentation";
import {
  Badge,
  Button,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";

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
 * The banner on the agent page: what the system did, when, and the buttons
 * that resolve it. Renders nothing when the agent is healthy.
 */
export function ScoutHealthBanner({
  config,
  onUpdate,
  onShowTab,
}: {
  config: ScoutConfig;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
  onShowTab: (tab: ScoutDetailTab) => void;
}) {
  const notice = scoutHealthNotice(config);
  if (!notice) return null;
  const changedAt = deriveScoutLifecycle(config).changedAt;
  const destructive = notice.tone === "destructive";
  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-(--radius-md) border px-3.5 py-2.5 ${
        destructive
          ? "border-(--red-6) bg-(--red-2)"
          : "border-(--amber-6) bg-(--amber-2)"
      }`}
      data-attr="scout-health-banner"
    >
      <p
        className={`min-w-0 flex-1 text-[12.5px] leading-snug ${
          destructive ? "text-(--red-11)" : "text-(--amber-11)"
        }`}
      >
        {notice.text}
        {changedAt ? (
          <>
            {" "}
            <RelativeTimestamp
              timestamp={changedAt}
              className={`text-[12px] ${destructive ? "text-(--red-10)" : "text-(--amber-10)"}`}
            />
          </>
        ) : null}
      </p>
      <div className="flex shrink-0 items-center gap-1.5">
        {notice.action === "resume" ? (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => onUpdate(config.id, { enabled: true })}
            data-attr="scout-health-resume"
          >
            Resume
          </Button>
        ) : null}
        {notice.action === "keep_running" ? (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => onUpdate(config.id, { auto_pause_exempt: true })}
            data-attr="scout-health-keep-running"
          >
            Keep running
          </Button>
        ) : null}
        {notice.link ? (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => onShowTab(notice.link as ScoutDetailTab)}
            data-attr="scout-health-open-tab"
          >
            {notice.link === "output" ? "Open output" : "Open runs"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
