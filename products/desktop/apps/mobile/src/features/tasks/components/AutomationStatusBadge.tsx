import { Text } from "@components/text";
import {
  type AutomationStatusTone,
  type AutomationTaskRunStatus,
  getAutomationStatusPresentation,
} from "@posthog/core/automations/automationStatus";
import { View } from "react-native";

/** The shared presentation names a tone; only the renderer knows the classes. */
const TONE_CLASSES: Record<
  AutomationStatusTone,
  { container: string; text: string }
> = {
  neutral: { container: "bg-gray-4", text: "text-gray-11" },
  warning: { container: "bg-status-warning/20", text: "text-status-warning" },
  success: { container: "bg-status-success/20", text: "text-status-success" },
  error: { container: "bg-status-error/20", text: "text-status-error" },
};

interface AutomationStatusBadgeProps {
  enabled: boolean;
  lastRunStatus: string | null;
  lastTaskRunStatus?: AutomationTaskRunStatus | null;
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
  const tone = runStatus ? TONE_CLASSES[runStatus.tone] : null;

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
      {runStatus && tone ? (
        <View className={`rounded px-1.5 py-0.5 ${tone.container}`}>
          <Text className={`text-xs ${tone.text}`}>{runStatus.label}</Text>
        </View>
      ) : null}
    </View>
  );
}
