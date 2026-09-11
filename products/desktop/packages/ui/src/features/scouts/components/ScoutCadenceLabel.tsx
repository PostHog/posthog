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
 * How often the scout runs, with the project timezone beside a schedule that picks hours of the
 * day: without it a reader in another timezone takes the time for their own.
 */
export function ScoutCadenceLabel({ config }: { config: ScoutConfig }) {
  const timezone = useProjectTimezone();
  const settingsUrl = projectTimezoneSettingsUrl();
  const label = formatScoutScheduleShort(config);
  if (!settingsUrl || !scoutScheduleNamesClockTime(config)) return <>{label}</>;

  // Still loading, or the request failed: a clock time is qualified either way.
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
                // The row and card around this label carry their own click targets.
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
