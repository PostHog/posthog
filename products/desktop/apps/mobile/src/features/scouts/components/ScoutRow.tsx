import { Text } from "@components/text";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  deriveScoutLifecycle,
  formatRunIntervalShort,
  prettifyScoutSkillName,
  type ScoutRollup,
} from "@posthog/core/scouts/scoutPresentation";
import { CaretDown, Play } from "phosphor-react-native";
import { ActivityIndicator, Pressable, Switch, View } from "react-native";
import { formatRelativeTime } from "@/lib/format";
import { useThemeColors } from "@/lib/theme";
import { describeLastRun, lifecycleBadgeClasses } from "../lib/scoutRows";

interface ScoutRowProps {
  config: ScoutConfig;
  rollup: ScoutRollup | undefined;
  /** Recomputed per render pass by the screen so relative times stay stable. */
  now: Date;
  isRunPending: boolean;
  onToggleEnabled: (config: ScoutConfig, enabled: boolean) => void;
  onPressRunNow: (config: ScoutConfig) => void;
  onPressInterval: (config: ScoutConfig) => void;
}

/**
 * One scout: what it is, how its last run went, and the three things a phone
 * is actually good for — switching it on or off, running it now, and changing
 * how often it runs. Per-run drill-down stays on desktop.
 */
export function ScoutRow({
  config,
  rollup,
  now,
  isRunPending,
  onToggleEnabled,
  onPressRunNow,
  onPressInterval,
}: ScoutRowProps) {
  const themeColors = useThemeColors();
  const lifecycle = deriveScoutLifecycle(config);
  const badge = lifecycle.label
    ? lifecycleBadgeClasses(lifecycle.lifecycle)
    : null;
  const lastRun = describeLastRun(rollup, now);
  const emittedCount = rollup?.emittedCount ?? 0;

  return (
    <View
      className={`mx-4 mb-2 rounded-lg border border-gray-5 bg-card px-3 py-3 ${
        config.enabled ? "" : "opacity-60"
      }`}
    >
      <View className="flex-row items-start gap-3">
        <View className="min-w-0 flex-1">
          <View className="flex-row items-center gap-2">
            <Text
              className="min-w-0 shrink font-medium text-[15px] text-gray-12"
              numberOfLines={1}
            >
              {prettifyScoutSkillName(config.skill_name)}
            </Text>
            {badge && lifecycle.label ? (
              <View className={`rounded px-1.5 py-0.5 ${badge.container}`}>
                <Text className={`text-[10px] ${badge.text}`}>
                  {lifecycle.label}
                </Text>
              </View>
            ) : null}
          </View>

          <Text className="mt-1 text-[12px] text-gray-10" numberOfLines={1}>
            {lastRun
              ? `${lastRun.label}${
                  lastRun.at !== null
                    ? ` · ${formatRelativeTime(lastRun.at)}`
                    : ""
                }`
              : "No runs in this window"}
          </Text>

          <Text className="mt-0.5 text-[12px] text-gray-10">
            {emittedCount} signal{emittedCount === 1 ? "" : "s"} emitted
          </Text>
        </View>

        <Switch
          value={config.enabled}
          onValueChange={(enabled) => onToggleEnabled(config, enabled)}
          accessibilityLabel={`${prettifyScoutSkillName(config.skill_name)} enabled`}
        />
      </View>

      {/* The system's explanation of a pause or warning is the whole reason the
          badge is there, so it stays on the row rather than behind a tap. */}
      {lifecycle.explanation ? (
        <Text className="mt-2 text-[12px] text-gray-11 leading-snug">
          {lifecycle.explanation}
        </Text>
      ) : null}

      <View className="mt-3 flex-row items-center gap-2">
        <Pressable
          onPress={() => onPressInterval(config)}
          className="flex-row items-center gap-1.5 rounded-lg border border-gray-5 px-2.5 py-1.5 active:bg-gray-2"
          accessibilityRole="button"
          accessibilityLabel={`${prettifyScoutSkillName(config.skill_name)} cadence`}
        >
          <Text className="text-[12px] text-gray-11">
            {formatRunIntervalShort(config.run_interval_minutes)}
          </Text>
          <CaretDown size={10} color={themeColors.gray[10]} />
        </Pressable>

        <Pressable
          onPress={() => onPressRunNow(config)}
          disabled={isRunPending}
          className={`flex-row items-center gap-1.5 rounded-lg border border-gray-5 px-2.5 py-1.5 ${
            isRunPending ? "opacity-50" : "active:bg-gray-2"
          }`}
          accessibilityRole="button"
          accessibilityLabel={`Run ${prettifyScoutSkillName(config.skill_name)} now`}
        >
          {isRunPending ? (
            <ActivityIndicator size="small" color={themeColors.gray[10]} />
          ) : (
            <Play size={12} color={themeColors.gray[11]} weight="fill" />
          )}
          <Text className="text-[12px] text-gray-11">Run now</Text>
        </Pressable>
      </View>
    </View>
  );
}
