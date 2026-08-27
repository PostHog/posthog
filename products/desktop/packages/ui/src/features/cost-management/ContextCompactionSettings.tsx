import {
  AUTO_COMPACT_DEFAULT_PERCENT,
  AUTO_COMPACT_MAX_PERCENT,
  AUTO_COMPACT_MIN_PERCENT,
} from "@posthog/core/sessions/autoCompact";
import { Slider, Switch, Text } from "@posthog/quill";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

export function ContextCompactionSettings() {
  const percent = useSettingsStore((state) => state.autoCompactPercent);
  const setPercent = useSettingsStore((state) => state.setAutoCompactPercent);
  const warnOnModelSwitch = useSettingsStore(
    (state) => state.warnOnMidSessionModelSwitch,
  );
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  return (
    <ContextCompactionSettingsView
      percent={percent}
      onChange={setPercent}
      warnOnModelSwitch={warnOnModelSwitch}
      onWarnOnModelSwitchChange={setWarnOnModelSwitch}
    />
  );
}

interface ContextCompactionSettingsViewProps {
  /** The threshold, or null when compaction is left to the model. */
  percent: number | null;
  onChange: (percent: number | null) => void;
  warnOnModelSwitch: boolean;
  onWarnOnModelSwitchChange: (enabled: boolean) => void;
}

export function ContextCompactionSettingsView({
  percent,
  onChange,
  warnOnModelSwitch,
  onWarnOnModelSwitchChange,
}: ContextCompactionSettingsViewProps) {
  const enabled = percent !== null;
  return (
    <SettingsSubsection
      title="Context"
      description="The model compacts a session on its own once the context is nearly full. Compacting sooner keeps every turn after it smaller."
    >
      <div className="flex flex-col gap-3 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) px-4 py-3.5">
        <div className="flex items-center justify-between gap-4">
          <span className="flex flex-col gap-0.5">
            <Text className="text-(--gray-12) text-[13px]">Compact early</Text>
            <Text className="text-(--gray-11) text-[12px]">
              Runs the same compaction you get from typing /compact, once a
              session passes the mark you set.
            </Text>
          </span>
          <Switch
            checked={enabled}
            onCheckedChange={(next) =>
              onChange(next ? AUTO_COMPACT_DEFAULT_PERCENT : null)
            }
            aria-label="Compact early"
            data-attr="cost-management-auto-compact-toggle"
          />
        </div>
        {enabled && (
          <div className="flex items-center gap-4 border-(--gray-4) border-t border-dashed pt-3.5">
            <Text className="shrink-0 text-(--gray-11) text-[12px]">
              Compact at
            </Text>
            <Slider
              className="flex-1"
              min={AUTO_COMPACT_MIN_PERCENT}
              max={AUTO_COMPACT_MAX_PERCENT}
              step={5}
              value={[percent ?? AUTO_COMPACT_DEFAULT_PERCENT]}
              onValueChange={(next) => {
                const value = Array.isArray(next) ? next[0] : next;
                if (typeof value === "number") onChange(value);
              }}
              aria-label="Compact when the context window passes this percent"
              data-attr="cost-management-auto-compact-percent"
            />
            <Text className="w-24 shrink-0 text-right text-(--gray-12) text-[12px] tabular-nums">
              {percent}% full
            </Text>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-3 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) px-4 py-3.5">
        <div className="flex items-center justify-between gap-4">
          <span className="flex flex-col gap-0.5">
            <Text className="text-(--gray-12) text-[13px]">
              Warn before a mid-session model switch
            </Text>
            <Text className="text-(--gray-11) text-[12px]">
              Switching models mid-session reprocesses the conversation instead
              of reading it from cache.
            </Text>
          </span>
          <Switch
            checked={warnOnModelSwitch}
            onCheckedChange={onWarnOnModelSwitchChange}
            aria-label="Warn before a mid-session model switch"
            data-attr="spend-limits-model-switch-warning-toggle"
          />
        </div>
      </div>
    </SettingsSubsection>
  );
}
