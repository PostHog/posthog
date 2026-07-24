import { Text } from "@components/text";
import { Plus } from "phosphor-react-native";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useAutomations } from "../hooks/useAutomations";
import { useTasks } from "../hooks/useTasks";
import type { TaskAutomation } from "../types";
import { AutomationItem } from "./AutomationItem";

interface AutomationListProps {
  onAutomationPress?: (automationId: string) => void;
  onCreateAutomation?: () => void;
  /** Top inset so the list can scroll behind a floating header. */
  contentInsetTop?: number;
}

function EmptyAutomationState({
  onCreateAutomation,
}: Pick<AutomationListProps, "onCreateAutomation">) {
  const themeColors = useThemeColors();

  return (
    <View className="flex-1 items-center justify-center p-6">
      <Text className="mb-2 text-center font-semibold text-gray-12 text-lg">
        No automations yet
      </Text>
      <Text className="mb-6 text-center text-gray-11 text-sm">
        Schedule recurring tasks
      </Text>
      {onCreateAutomation && (
        <Pressable
          onPress={onCreateAutomation}
          className="flex-row items-center gap-2 rounded-full px-6 py-3.5 active:opacity-80"
          style={{ backgroundColor: themeColors.accent[9] }}
        >
          <Plus size={18} color={themeColors.accent.contrast} weight="bold" />
          <Text className="font-semibold text-[15px] text-accent-contrast">
            New automation
          </Text>
        </Pressable>
      )}
    </View>
  );
}

export function AutomationList({
  onAutomationPress,
  onCreateAutomation,
  contentInsetTop = 0,
}: AutomationListProps) {
  const { automations, isLoading, error, refetch } = useAutomations();
  const { allTasks: automationTasks } = useTasks({
    originProduct: "automation",
  });
  const themeColors = useThemeColors();

  const handleRefresh = async () => {
    await refetch();
  };

  const handleAutomationPress = (automation: TaskAutomation) => {
    onAutomationPress?.(automation.id);
  };

  const taskStatusById = new Map(
    automationTasks.map((task) => [task.id, task.latest_run?.status ?? null]),
  );

  if (error) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <Text className="mb-4 text-center text-status-error">{error}</Text>
        <Pressable
          onPress={handleRefresh}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (isLoading && automations.length === 0) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
        <Text className="mt-4 text-gray-11">Loading automations...</Text>
      </View>
    );
  }

  if (automations.length === 0) {
    return <EmptyAutomationState onCreateAutomation={onCreateAutomation} />;
  }

  return (
    <FlatList
      data={automations}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => (
        <AutomationItem
          automation={item}
          onPress={handleAutomationPress}
          lastTaskRunStatus={
            item.last_task_id
              ? (taskStatusById.get(item.last_task_id) ?? null)
              : null
          }
        />
      )}
      refreshControl={
        <RefreshControl
          refreshing={isLoading}
          onRefresh={handleRefresh}
          tintColor={themeColors.accent[9]}
        />
      }
      contentContainerStyle={{
        paddingTop: contentInsetTop,
        paddingBottom: 100,
      }}
    />
  );
}
