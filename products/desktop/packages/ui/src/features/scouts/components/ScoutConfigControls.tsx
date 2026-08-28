import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  deriveScoutLifecycle,
  formatRunInterval,
  RUN_INTERVAL_OPTIONS,
} from "@posthog/core/scouts/scoutPresentation";
import { Switch as QuillSwitch, Text as QuillText } from "@posthog/quill";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { Flex, Switch, Text, Tooltip } from "@radix-ui/themes";
import { useMemo } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";

const MODE_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "dry_run", label: "Dry run" },
];

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
    ? "Disable scout"
    : deriveScoutLifecycle(config).isSystemPaused
      ? "Resume scout"
      : "Enable scout";
  return (
    <Tooltip content={tooltip}>
      {/* Tooltip stamps its own data-state on its child, which would overwrite
          the Switch's checked/unchecked state and leave the track stuck on the
          accent color. Give it a span to stamp. */}
      <span className="inline-flex">
        <Switch
          size="1"
          checked={config.enabled}
          onCheckedChange={(checked) =>
            onUpdate(config.id, { enabled: checked })
          }
          aria-label={`${config.skill_name} enabled`}
        />
      </span>
    </Tooltip>
  );
}

/**
 * Labeled settings form for one scout, shown when a fleet row's gear is
 * toggled open. Everything except enablement, which stays on the row.
 */
export function ScoutConfigForm({
  config,
  onUpdate,
}: ScoutConfigControlsProps) {
  const intervalOptions = useIntervalOptions(config);
  const lifecycle = deriveScoutLifecycle(config);

  return (
    <Flex direction="column" gap="2">
      <Flex align="center" justify="between" gap="4">
        <Flex direction="column" className="min-w-0">
          <Text className="text-[12px] text-gray-12">Mode</Text>
          <Text className="text-[11.5px] text-gray-10">
            Dry run executes the scout but holds back its signals
          </Text>
        </Flex>
        <SettingsOptionSelect
          value={config.emit ? "live" : "dry_run"}
          options={MODE_OPTIONS}
          ariaLabel={`${config.skill_name} mode`}
          disabled={!config.enabled}
          className="w-24"
          onValueChange={(value) =>
            onUpdate(config.id, { emit: value === "live" })
          }
        />
      </Flex>
      <Flex align="center" justify="between" gap="4">
        <Flex direction="column" className="min-w-0">
          <Text className="text-[12px] text-gray-12">Cadence</Text>
          <Text className="text-[11.5px] text-gray-10">
            How often the scout is dispatched
          </Text>
        </Flex>
        <SettingsOptionSelect
          value={String(config.run_interval_minutes)}
          options={intervalOptions}
          ariaLabel={`${config.skill_name} run interval`}
          disabled={!config.enabled}
          className="w-36"
          onValueChange={(value) =>
            onUpdate(config.id, { run_interval_minutes: Number(value) })
          }
        />
      </Flex>
      {/* Null means the backend never sent the field, so a PATCH carrying it
          could not persist. Offer the control only where it writes. */}
      {lifecycle.autoPauseExempt !== null ? (
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 flex-col">
            <QuillText size="xs" className="text-gray-12">
              Never pause for inactivity
            </QuillText>
            <QuillText size="xxs" className="text-gray-10">
              Keep running when the scout goes quiet or its findings go unacted
              on. Repeated failures still pause it.
            </QuillText>
          </div>
          <QuillSwitch
            size="sm"
            checked={lifecycle.autoPauseExempt}
            onCheckedChange={(checked) =>
              onUpdate(config.id, { auto_pause_exempt: checked })
            }
            aria-label={`${config.skill_name} exempt from inactivity pauses`}
          />
        </div>
      ) : null}
    </Flex>
  );
}
