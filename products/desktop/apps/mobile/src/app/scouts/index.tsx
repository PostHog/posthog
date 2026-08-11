import { FloatingScreenHeader } from "@components/FloatingScreenHeader";
import { Text } from "@components/text";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  computeFleetSummary,
  computeScoutRollups,
  prettifyScoutSkillName,
  sortConfigsForDisplay,
} from "@posthog/core/scouts/scoutPresentation";
import {
  SCOUT_RUNS_WINDOW_SPAN,
  scoutRunsWindowLabel,
} from "@posthog/core/scouts/scoutRunsWindow";
import { Binoculars } from "phosphor-react-native";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { ScoutFleetSummary } from "@/features/scouts/components/ScoutFleetSummary";
import { ScoutRow } from "@/features/scouts/components/ScoutRow";
import {
  useScoutConfigMutations,
  useScoutConfigs,
  useScoutRuns,
} from "@/features/scouts/hooks";
import { intervalOptions } from "@/features/scouts/lib/scoutRows";
import { SelectSheet } from "@/features/tasks/composer/SelectSheet";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

export default function ScoutsScreen() {
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const configsQuery = useScoutConfigs();
  const runsQuery = useScoutRuns();
  const { updateConfig, runScout } = useScoutConfigMutations();
  const [intervalTarget, setIntervalTarget] = useState<ScoutConfig | null>(
    null,
  );

  const configs = useMemo(
    () => sortConfigsForDisplay(configsQuery.data ?? []),
    [configsQuery.data],
  );
  const runs = runsQuery.data?.runs;
  const rollups = useMemo(() => computeScoutRollups(runs ?? []), [runs]);
  const summary = useMemo(
    () => computeFleetSummary(configs, rollups),
    [configs, rollups],
  );
  // One clock per render pass so every row's relative time and run outcome are
  // derived from the same instant.
  const now = useMemo(() => new Date(), []);

  const handleToggleEnabled = useCallback(
    (config: ScoutConfig, enabled: boolean) => {
      // `enabled` carries the pause semantics: off records a user pause the
      // system never overrides, on resumes from any pause including a system one.
      updateConfig.mutate({ configId: config.id, updates: { enabled } });
    },
    [updateConfig],
  );

  const handleRunNow = useCallback(
    (config: ScoutConfig) => {
      runScout.mutate(config.id, {
        onSuccess: () =>
          Alert.alert(
            "Run started",
            `${prettifyScoutSkillName(config.skill_name)} is running now. Its result appears here once the run finishes.`,
          ),
        // The server explains the expected rejections (already running, over
        // quota) in its own words — pass them straight through.
        onError: (error) => Alert.alert("Couldn't run scout", error.message),
      });
    },
    [runScout],
  );

  const handleChangeInterval = useCallback(
    (value: string) => {
      if (!intervalTarget) return;
      updateConfig.mutate({
        configId: intervalTarget.id,
        updates: { run_interval_minutes: Number(value) },
      });
    },
    [intervalTarget, updateConfig],
  );

  const isRefreshing = configsQuery.isRefetching || runsQuery.isRefetching;
  const handleRefresh = useCallback(() => {
    configsQuery.refetch();
    runsQuery.refetch();
  }, [configsQuery, runsQuery]);

  return (
    <View className="flex-1 bg-background">
      <FloatingScreenHeader title="Scouts" />

      <View className="flex-1" style={{ paddingTop: insets.top + 60 }}>
        {configsQuery.isPending ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator color={themeColors.accent[9]} />
          </View>
        ) : configsQuery.isError ? (
          // A failed request must not read as an empty fleet: a missing scope
          // or a rollout gap would be indistinguishable from "no scouts yet".
          <FleetError onRetry={() => configsQuery.refetch()} />
        ) : (
          <FlatList
            data={configs}
            keyExtractor={(config) => config.id}
            ListHeaderComponent={
              configs.length > 0 ? (
                <ScoutFleetSummary
                  summary={summary}
                  windowLabel={scoutRunsWindowLabel(runsQuery.data)}
                />
              ) : null
            }
            renderItem={({ item }) => (
              <ScoutRow
                config={item}
                rollup={rollups.get(item.skill_name)}
                now={now}
                isRunPending={
                  runScout.isPending && runScout.variables === item.id
                }
                onToggleEnabled={handleToggleEnabled}
                onPressRunNow={handleRunNow}
                onPressInterval={setIntervalTarget}
              />
            )}
            ListEmptyComponent={<FleetEmpty />}
            refreshControl={
              <RefreshControl
                refreshing={isRefreshing}
                onRefresh={handleRefresh}
                tintColor={themeColors.accent[9]}
              />
            }
            contentContainerStyle={{ paddingBottom: bottom("default") }}
          />
        )}
      </View>

      <SelectSheet
        open={intervalTarget !== null}
        title="Cadence"
        value={
          intervalTarget ? String(intervalTarget.run_interval_minutes) : ""
        }
        onChange={handleChangeInterval}
        onClose={() => setIntervalTarget(null)}
        options={intervalTarget ? intervalOptions(intervalTarget) : []}
      />
    </View>
  );
}

function FleetError({ onRetry }: { onRetry: () => void }) {
  return (
    <View className="items-center px-8 py-16">
      <Text className="mb-4 text-center text-[13px] text-status-error leading-snug">
        Couldn't load the scout fleet. The scout API may be unavailable, or this
        login may not be authorized for it — signing out and back in re-grants
        the scout scopes.
      </Text>
      <Pressable
        onPress={onRetry}
        className="rounded-lg bg-gray-3 px-4 py-2 active:opacity-80"
      >
        <Text className="font-medium text-[14px] text-gray-12">Retry</Text>
      </Pressable>
    </View>
  );
}

function FleetEmpty() {
  const themeColors = useThemeColors();
  return (
    <View className="items-center px-8 py-16">
      <View className="mb-4 h-12 w-12 items-center justify-center rounded-full bg-gray-3">
        <Binoculars size={22} color={themeColors.gray[11]} weight="bold" />
      </View>
      <Text className="mb-1 font-semibold text-[16px] text-gray-12">
        No scouts on this project yet
      </Text>
      <Text className="text-center text-[13px] text-gray-10 leading-snug">
        Scouts watch your project and raise findings on their own. Once this
        project is enrolled the fleet appears here, with the last{" "}
        {SCOUT_RUNS_WINDOW_SPAN} of runs.
      </Text>
    </View>
  );
}
