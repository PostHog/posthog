import { Text } from "@components/text";
import { format, formatDistanceToNow } from "date-fns";
import { memo } from "react";
import { Pressable, View } from "react-native";
import type { TaskAutomation, TaskRun } from "../types";
import { formatAutomationScheduleSummary } from "../utils/automationSchedule";
import { getAutomationTemplatePresentation } from "../utils/automationTemplatePresentation";
import { AutomationStatusBadge } from "./AutomationStatusBadge";

interface AutomationItemProps {
  automation: TaskAutomation;
  onPress: (automation: TaskAutomation) => void;
  lastTaskRunStatus?: TaskRun["status"] | null;
}

function AutomationItemComponent({
  automation,
  onPress,
  lastTaskRunStatus,
}: AutomationItemProps) {
  const presentation = getAutomationTemplatePresentation(automation);
  const lastRunDisplay = automation.last_run_at
    ? new Date(automation.last_run_at).getTime() >
      Date.now() - 24 * 60 * 60 * 1000
      ? formatDistanceToNow(new Date(automation.last_run_at), {
          addSuffix: true,
        })
      : format(new Date(automation.last_run_at), "MMM d")
    : "No runs yet";

  return (
    <Pressable
      onPress={() => onPress(automation)}
      className="border-gray-6 border-b px-3 py-3 active:bg-gray-3"
    >
      <View className="flex-row items-center justify-between gap-3">
        <Text
          className="flex-1 font-medium text-gray-12 text-sm"
          numberOfLines={1}
        >
          {automation.name}
        </Text>
        <Text className="text-gray-8 text-xs">{lastRunDisplay}</Text>
      </View>

      <View className="mt-1">
        <AutomationStatusBadge
          enabled={automation.enabled}
          lastRunStatus={automation.last_run_status}
          lastTaskRunStatus={lastTaskRunStatus}
        />
      </View>

      <Text className="mt-2 text-gray-11 text-xs" numberOfLines={1}>
        {presentation.secondaryLabel}
      </Text>
      <Text className="mt-0.5 text-gray-9 text-xs" numberOfLines={1}>
        {formatAutomationScheduleSummary(automation)}
      </Text>

      {automation.last_error && (
        <Text className="mt-2 text-status-error text-xs" numberOfLines={2}>
          {automation.last_error}
        </Text>
      )}
    </Pressable>
  );
}

export const AutomationItem = memo(AutomationItemComponent);
