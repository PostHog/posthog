import type {
  ScoutSuggestionItem,
  ScoutSuggestionProposedConfig,
} from "@posthog/api-client/posthog-client";
import { formatScoutScheduleShort } from "./scoutPresentation";

/** Minutes between runs for a suggestion that names no schedule of its own. */
export const DEFAULT_SUGGESTION_INTERVAL_MINUTES = 1440;

/** How often the suggested agent would run, in the roster's own words. */
export function suggestionCadenceLabel(
  config: ScoutSuggestionProposedConfig,
): string {
  return formatScoutScheduleShort({
    run_cron_schedule: config.run_cron_schedule,
    run_interval_minutes:
      config.run_interval_minutes ?? DEFAULT_SUGGESTION_INTERVAL_MINUTES,
  });
}

/** One line on what the agent would do: how often, and where its output goes. */
export function suggestionMetaLine(
  config: ScoutSuggestionProposedConfig,
): string {
  const output = config.emit
    ? "sends what it finds to Self-driving"
    : "dry run, sends nothing";
  return `Runs ${suggestionCadenceLabel(config)} · ${output}`;
}

/** What the primary action on a suggestion does. */
export function suggestionActionLabel(item: ScoutSuggestionItem): string {
  return item.kind === "canonical" ? "Turn on" : "Draft it";
}

/**
 * The brief a custom draft hands the authoring chat. The title says what to
 * watch and the description carries the shape, so the chat starts from the
 * suggestion rather than from an empty box.
 */
export function suggestionBrief(item: ScoutSuggestionItem): string {
  const description = item.description.trim();
  return description ? `${item.title}. ${description}` : item.title;
}
