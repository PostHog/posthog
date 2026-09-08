import { SparkleIcon } from "@phosphor-icons/react";
import type {
  ScoutConfig,
  ScoutSuggestionItem,
} from "@posthog/api-client/posthog-client";
import { scoutSkillSlug } from "@posthog/core/scouts/scoutPresentation";
import {
  suggestionActionLabel,
  suggestionMetaLine,
} from "@posthog/core/scouts/scoutSuggestions";
import { Badge, Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { track } from "@posthog/ui/shell/analytics";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";

/**
 * What PostHog thinks should watch this project, with the evidence it found.
 * A canonical pick turns an agent that already exists back on; a custom draft
 * hands its brief to the authoring chat. Both leave the list once acted on.
 */
export function ScoutSuggestions({
  items,
  configs,
  onTurnOn,
  onDraft,
  onDismiss,
}: {
  items: ScoutSuggestionItem[];
  /** The fleet, for resolving which agent a canonical pick would switch on. */
  configs: ScoutConfig[];
  onTurnOn: (configId: string, updates: ScoutConfigUpdate) => void;
  onDraft: (item: ScoutSuggestionItem) => void;
  onDismiss: (item: ScoutSuggestionItem) => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <SparkleIcon size={13} className="text-(--iris-11)" />
        <h2 className="font-semibold text-[13px] text-gray-12">
          Suggested for this project
        </h2>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => (
          <SuggestionCard
            key={item.id}
            item={item}
            config={configs.find(
              (config) => config.skill_name === item.skill_name,
            )}
            onTurnOn={onTurnOn}
            onDraft={onDraft}
            onDismiss={onDismiss}
          />
        ))}
      </div>
    </section>
  );
}

function SuggestionCard({
  item,
  config,
  onTurnOn,
  onDraft,
  onDismiss,
}: {
  item: ScoutSuggestionItem;
  config: ScoutConfig | undefined;
  onTurnOn: (configId: string, updates: ScoutConfigUpdate) => void;
  onDraft: (item: ScoutSuggestionItem) => void;
  onDismiss: (item: ScoutSuggestionItem) => void;
}) {
  // A canonical pick names an agent this project already has, off. Without that
  // agent there is nothing to switch on, so the card offers the draft instead.
  const canTurnOn = item.kind === "canonical" && config !== undefined;

  const act = () => {
    track(ANALYTICS_EVENTS.SCOUT_ACTION, {
      action_type: canTurnOn ? "accept_suggestion" : "draft_suggestion",
      surface: "fleet_list",
      skill_name: item.skill_name,
    });
    if (canTurnOn && config) {
      onTurnOn(config.id, { enabled: true });
    } else {
      onDraft(item);
    }
    onDismiss(item);
  };

  return (
    <div className="flex flex-col gap-2 rounded-(--radius-md) border border-border bg-(--color-panel-solid) px-3.5 py-3">
      <div className="flex min-w-0 items-start gap-2">
        <span className="min-w-0 flex-1 font-medium text-[13px] text-gray-12 leading-snug">
          {item.title}
        </span>
        {item.gap ? <Badge variant="info">New ground</Badge> : null}
      </div>
      <p className="line-clamp-3 text-[11.5px] text-gray-10 leading-snug">
        {item.why_here}
      </p>
      <span className="text-[11px] text-gray-9">
        {suggestionMetaLine(item.proposed_config)}
      </span>
      <div className="mt-1 flex items-center gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="xs"
          onClick={act}
          data-attr={`scout-suggestion-${scoutSkillSlug(item.skill_name)}`}
        >
          {canTurnOn ? suggestionActionLabel(item) : "Draft it"}
        </Button>
        <Button
          type="button"
          variant="link-muted"
          size="xs"
          onClick={() => {
            track(ANALYTICS_EVENTS.SCOUT_ACTION, {
              action_type: "dismiss_suggestion",
              surface: "fleet_list",
              skill_name: item.skill_name,
            });
            onDismiss(item);
          }}
        >
          Not now
        </Button>
      </div>
    </div>
  );
}
