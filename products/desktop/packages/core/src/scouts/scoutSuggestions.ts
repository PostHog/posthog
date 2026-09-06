import type {
  ScoutConfig,
  ScoutCreateInput,
  ScoutSuggestionItem,
  ScoutSuggestionProposedConfig,
} from "@posthog/api-client/posthog-client";
import { formatScoutScheduleShort } from "./scoutPresentation";

/** Cadence a pick that names no schedule of its own would be created with. */
export const DEFAULT_SUGGESTION_INTERVAL_MINUTES = 1440;

/** How often the suggested scout would run, in the roster's own words. */
export function suggestionCadenceLabel(
  config: ScoutSuggestionProposedConfig,
): string {
  return formatScoutScheduleShort({
    run_cron_schedule: config.run_cron_schedule,
    run_interval_minutes:
      config.run_interval_minutes ?? DEFAULT_SUGGESTION_INTERVAL_MINUTES,
  });
}

/** One-line summary of what the scout would do: how often, and where its output goes. */
export function suggestionMetaLine(
  config: ScoutSuggestionProposedConfig,
): string {
  const output = config.emit
    ? "files reports to the inbox"
    : "dry run, files nothing";
  return `Runs ${suggestionCadenceLabel(config)} · ${output}`;
}

/**
 * The picks still worth offering. The read already drops dismissed and created
 * ones, so this covers the gap until the next read: a pick the person just
 * dismissed, and a canonical scout the roster has since switched on.
 */
export function visibleScoutSuggestions(
  items: ScoutSuggestionItem[],
  { hiddenIds, configs }: { hiddenIds: string[]; configs: ScoutConfig[] },
): ScoutSuggestionItem[] {
  const enabled = new Set(
    configs
      .filter((config) => config.enabled)
      .map((config) => config.skill_name),
  );
  return items.filter(
    (item) => !hiddenIds.includes(item.id) && !enabled.has(item.skill_name),
  );
}

/** The create-a-scout body a custom pick would be created with. */
export function suggestionToCreateInput(
  item: ScoutSuggestionItem,
): ScoutCreateInput {
  const proposed = item.proposed_config;
  return {
    name: item.skill_name,
    description: item.description,
    body: item.draft_body,
    config: {
      enabled: true,
      emit: proposed.emit,
      run_cron_schedule: proposed.run_cron_schedule,
      run_interval_minutes:
        proposed.run_interval_minutes ?? DEFAULT_SUGGESTION_INTERVAL_MINUTES,
    },
    suggestion_id: item.id,
  };
}
