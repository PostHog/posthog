import { Text } from "@components/text";
import { View } from "react-native";
import type { TaskRun } from "../types";
import { getAutomationStatusPresentation } from "../utils/automationStatus";

interface AutomationStatusBadgeProps {
  enabled: boolean;
  lastRunStatus: string | null;
  lastTaskRunStatus?: TaskRun["status"] | null;
}

export function AutomationStatusBadge({
  enabled,
  lastRunStatus,
  lastTaskRunStatus,
}: AutomationStatusBadgeProps) {
  const runStatus = getAutomationStatusPresentation({
    lastRunStatus,
    lastTaskRunStatus,
  });

  return (
    <View className="flex-row flex-wrap gap-2">
      <View
        className={`rounded px-1.5 py-0.5 ${
          enabled ? "bg-accent-3" : "bg-gray-4"
        }`}
      >
        <Text
          className={`text-xs ${enabled ? "text-accent-11" : "text-gray-11"}`}
        >
          {enabled ? "Enabled" : "Paused"}
        </Text>
      </View>
      {runStatus ? (
        <View className={`rounded px-1.5 py-0.5 ${runStatus.className}`}>
          <Text className={`text-xs ${runStatus.className.split(" ")[1]}`}>
            {runStatus.label}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
