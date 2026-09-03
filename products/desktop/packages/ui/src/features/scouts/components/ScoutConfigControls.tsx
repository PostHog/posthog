import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  deriveScoutLifecycle,
  formatNextRun,
  formatRunInterval,
  getScoutOrigin,
  nextRunAt,
  RUN_INTERVAL_OPTIONS,
} from "@posthog/core/scouts/scoutPresentation";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { RadioCards } from "@posthog/ui/primitives/RadioCards";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { skillUrl } from "@posthog/ui/utils/posthogLinks";
import { type ReactNode, useMemo } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { ScoutHelperSkillLinks } from "./ScoutHelperSkillLinks";

const MODE_OPTIONS = [
  {
    value: "live",
    title: "Live",
    description: "Signals reach Self-driving as soon as the agent finds them.",
  },
  {
    value: "dry_run",
    title: "Dry run",
    description:
      "Runs on schedule and records what it would send. Nothing leaves this page.",
  },
] as const;

interface ScoutConfigControlsProps {
  config: ScoutConfig;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
}

function useIntervalOptions(config: ScoutConfig) {
  return useMemo(() => {
    const options = RUN_INTERVAL_OPTIONS.map((option) => ({
      value: String(option.minutes),
      label: option.label,
    }));
    if (
      !RUN_INTERVAL_OPTIONS.some(
        (option) => option.minutes === config.run_interval_minutes,
      )
    ) {
      options.push({
        value: String(config.run_interval_minutes),
        label: formatRunInterval(config.run_interval_minutes),
      });
    }
    return options;
  }, [config.run_interval_minutes]);
}

export function ScoutEnabledSwitch({
  config,
  onUpdate,
}: ScoutConfigControlsProps) {
  // Switching a system-paused scout back on is the documented recovery, so say
  // "resume" rather than the generic "enable"; the badge beside it explains why
  // the scout stopped.
  const tooltip = config.enabled
    ? "Switch this agent off"
    : deriveScoutLifecycle(config).isSystemPaused
      ? "Resume this agent"
      : "Switch this agent on";
  return (
    <Tooltip content={tooltip}>
      <span className="inline-flex">
        <Switch
          size="sm"
          checked={config.enabled}
          onCheckedChange={(checked) =>
            onUpdate(config.id, { enabled: checked })
          }
          aria-label={`${config.skill_name} enabled`}
          data-attr="scout-enabled"
        />
      </span>
    </Tooltip>
  );
}

/** The Settings tab of the agent page. Every change saves as it is made. */
export function ScoutConfigForm({
  config,
  onUpdate,
}: ScoutConfigControlsProps) {
  const intervalOptions = useIntervalOptions(config);
  const lifecycle = deriveScoutLifecycle(config);
  const cloudSkillUrl = skillUrl(config.skill_name);
  const next = formatNextRun(nextRunAt(config), new Date());
  const canonical = getScoutOrigin(config) === "canonical";
  const instructions = config.description?.trim();

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-7">
      <SettingBlock
        title="Instructions"
        help={
          canonical
            ? "What this agent looks for. PostHog maintains built-in agents. To change one, ask PostHog to create a custom agent based on it."
            : "What this agent looks for. Edit the skill in PostHog to change what it watches and when it sends a signal."
        }
      >
        <div className="flex flex-col rounded-(--radius-md) border border-border bg-(--color-panel-solid)">
          {instructions ? (
            <p className="whitespace-pre-wrap px-3.5 py-3 text-[12.5px] text-gray-11 leading-relaxed">
              {instructions}
            </p>
          ) : (
            <p className="px-3.5 py-3 text-[12.5px] text-gray-10">
              This skill has no description.
            </p>
          )}
          <div className="flex items-center justify-between gap-3 border-(--gray-4) border-t px-3.5 py-2.5">
            <div className="flex min-w-0 flex-col gap-1">
              <code className="truncate text-[11.5px] text-gray-11">
                {config.skill_name}
              </code>
              <ScoutHelperSkillLinks surface="scout_detail" />
            </div>
            {cloudSkillUrl ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => {
                  track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                    action_type: "open_skill_in_posthog",
                    surface: "scout_detail",
                    skill_name: config.skill_name,
                  });
                  window.open(cloudSkillUrl, "_blank", "noreferrer");
                }}
              >
                <ArrowSquareOutIcon size={13} />
                {canonical ? "Open in PostHog" : "Edit in PostHog"}
              </Button>
            ) : null}
          </div>
        </div>
      </SettingBlock>

      <SettingBlock
        title="Mode"
        help="Use Dry run to check a new or changed agent before its signals reach anyone."
      >
        <RadioCards
          value={config.emit ? "live" : "dry_run"}
          options={MODE_OPTIONS}
          onChange={(value) => onUpdate(config.id, { emit: value === "live" })}
          ariaLabel={`${config.skill_name} mode`}
          dataAttrPrefix="scout-mode"
        />
      </SettingBlock>

      <SettingBlock
        title="Schedule"
        help={
          next
            ? `Next run ${next}. Changing the schedule takes effect after that run.`
            : "How often PostHog dispatches this agent."
        }
      >
        <div className="w-48">
          <SettingsOptionSelect
            value={String(config.run_interval_minutes)}
            options={intervalOptions}
            ariaLabel={`${config.skill_name} run interval`}
            size="default"
            onValueChange={(value) =>
              onUpdate(config.id, { run_interval_minutes: Number(value) })
            }
          />
        </div>
      </SettingBlock>

      {/* Null means the backend never sent the field, so a PATCH carrying it
          could not persist. Offer the control only where it writes. */}
      {lifecycle.autoPauseExempt !== null ? (
        <SettingBlock
          title="Auto-pause"
          help="PostHog pauses agents that stay quiet or whose signals nobody acts on. Repeated failures pause an agent either way."
        >
          <div className="flex items-center justify-between gap-4 rounded-(--radius-md) border border-border bg-(--color-panel-solid) px-3.5 py-3">
            <span className="flex min-w-0 flex-col">
              <span className="text-[12.5px] text-gray-12">
                Never pause for inactivity
              </span>
              <span className="text-[11.5px] text-gray-10">
                For agents whose job is to stay quiet until something breaks.
              </span>
            </span>
            <Switch
              size="sm"
              checked={lifecycle.autoPauseExempt}
              onCheckedChange={(checked) =>
                onUpdate(config.id, { auto_pause_exempt: checked })
              }
              aria-label={`${config.skill_name} exempt from inactivity pauses`}
              data-attr="scout-auto-pause-exempt"
            />
          </div>
        </SettingBlock>
      ) : null}
    </div>
  );
}

function SettingBlock({
  title,
  help,
  children,
}: {
  title: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5">
        <h2 className="font-semibold text-[13px] text-gray-12">{title}</h2>
        <p className="text-[11.5px] text-gray-10 leading-snug">{help}</p>
      </div>
      {children}
    </section>
  );
}
