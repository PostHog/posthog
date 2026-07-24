import { Text } from "@components/text";
import { ActivityIndicator, Pressable, View } from "react-native";
import type { TaskAutomation, TaskRun } from "../types";
import { formatAutomationScheduleSummary } from "../utils/automationSchedule";
import { getAutomationTemplatePresentation } from "../utils/automationTemplatePresentation";
import { AutomationStatusBadge } from "./AutomationStatusBadge";

interface AutomationDetailProps {
  automation: TaskAutomation;
  lastTaskRunStatus?: TaskRun["status"] | null;
  isWorking?: boolean;
  onRunNow: () => void;
  onToggleEnabled: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export function AutomationDetail({
  automation,
  lastTaskRunStatus,
  isWorking = false,
  onRunNow,
  onToggleEnabled,
  onEdit,
  onDelete,
}: AutomationDetailProps) {
  const presentation = getAutomationTemplatePresentation(automation);

  return (
    <View>
      <View className="rounded-xl border border-gray-6 bg-gray-1 px-4 py-4">
        <Text className="font-semibold text-gray-12 text-lg">
          {automation.name}
        </Text>
        <View className="mt-3">
          <AutomationStatusBadge
            enabled={automation.enabled}
            lastRunStatus={automation.last_run_status}
            lastTaskRunStatus={lastTaskRunStatus}
          />
        </View>

        <View className="mt-4 gap-3">
          {presentation.templateName && (
            <View>
              <Text className="text-gray-9 text-xs">Template</Text>
              <Text className="mt-1 text-gray-12 text-sm">
                {presentation.templateName}
              </Text>
            </View>
          )}
          {presentation.repositoryLabel ? (
            <View>
              <Text className="text-gray-9 text-xs">Repository</Text>
              <Text className="mt-1 text-gray-12 text-sm">
                {presentation.repositoryLabel}
              </Text>
            </View>
          ) : presentation.contextLabel ? (
            <View>
              <Text className="text-gray-9 text-xs">Context</Text>
              <Text className="mt-1 text-gray-12 text-sm">
                {presentation.contextLabel}
              </Text>
            </View>
          ) : null}
          <View>
            <Text className="text-gray-9 text-xs">Schedule</Text>
            <Text className="mt-1 text-gray-12 text-sm">
              {formatAutomationScheduleSummary(automation)}
            </Text>
          </View>
          <View>
            <Text className="text-gray-9 text-xs">Prompt</Text>
            <Text className="mt-1 text-gray-12 text-sm">
              {automation.prompt}
            </Text>
          </View>
          <View>
            <Text className="text-gray-9 text-xs">Last task</Text>
            <Text className="mt-1 text-gray-12 text-sm">
              {automation.last_task_id ?? "No runs yet"}
            </Text>
          </View>
        </View>

        {automation.last_error && (
          <View className="mt-4 rounded-lg bg-status-error/10 px-3 py-3">
            <Text className="text-status-error text-xs">Last error</Text>
            <Text className="mt-1 text-sm text-status-error">
              {automation.last_error}
            </Text>
          </View>
        )}
      </View>

      <View className="mt-4 gap-3">
        <Pressable
          onPress={onRunNow}
          disabled={isWorking}
          className="rounded-lg bg-accent-9 py-3"
        >
          {isWorking ? (
            <ActivityIndicator size="small" color="white" />
          ) : (
            <Text className="text-center font-medium text-accent-contrast">
              Run now
            </Text>
          )}
        </Pressable>

        <View className="flex-row gap-3">
          <Pressable
            onPress={onEdit}
            className="flex-1 rounded-lg border border-gray-6 py-3"
          >
            <Text className="text-center font-medium text-gray-12">Edit</Text>
          </Pressable>
          <Pressable
            onPress={onToggleEnabled}
            className="flex-1 rounded-lg border border-gray-6 py-3"
          >
            <Text className="text-center font-medium text-gray-12">
              {automation.enabled ? "Pause" : "Resume"}
            </Text>
          </Pressable>
        </View>

        <Pressable
          onPress={onDelete}
          className="rounded-lg border border-status-error/30 py-3"
        >
          <Text className="text-center font-medium text-status-error">
            Delete automation
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
