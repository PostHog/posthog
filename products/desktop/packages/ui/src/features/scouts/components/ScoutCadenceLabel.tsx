import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  formatScoutScheduleShort,
  scoutScheduleNamesClockTime,
} from "@posthog/core/scouts/scoutPresentation";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { useProjectTimezone } from "@posthog/ui/features/projects/useProjectTimezone";
import { formatTimezoneAbbreviation } from "@posthog/ui/primitives/timezone";
import { projectTimezoneSettingsUrl } from "@posthog/ui/utils/posthogLinks";

/**
 * How often the scout runs. A schedule that picks hours of the day carries the project timezone
 * next to it, because the coordinator resolves the schedule in that timezone. Without it, a
 * reader in another timezone reads the time as their own and thinks the scout runs late.
 */
export function ScoutCadenceLabel({ config }: { config: ScoutConfig }) {
  const timezone = useProjectTimezone();
  const settingsUrl = projectTimezoneSettingsUrl();
  const label = formatScoutScheduleShort(config);
  if (!settingsUrl || !scoutScheduleNamesClockTime(config)) return <>{label}</>;

  // The timezone is still loading, or its request failed. Say the time belongs to the project
  // either way, so nobody takes an unqualified time for their own.
  const suffix = timezone
    ? formatTimezoneAbbreviation(timezone)
    : "project timezone";
  const tooltip = timezone
    ? `Times use the project timezone (${timezone}). Open settings to change it.`
    : "Times use the project timezone. Open settings to see or change it.";

  return (
    <>
      {label}{" "}
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                className="appearance-none border-0 bg-transparent p-0 text-gray-10 underline decoration-dotted underline-offset-2"
                // The row and the card around this label carry their own click targets, so the
                // settings hop stops here rather than opening the scout as well.
                onClick={(event) => {
                  event.stopPropagation();
                  window.open(settingsUrl, "_blank", "noreferrer");
                }}
              >
                ({suffix})
              </button>
            }
          />
          <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </>
  );
}
