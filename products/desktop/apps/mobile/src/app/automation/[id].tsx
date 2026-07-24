import { Text } from "@components/text";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { TaskAutomationValidationError } from "@/features/tasks/api";
import { AutomationDetail } from "@/features/tasks/components/AutomationDetail";
import { AutomationForm } from "@/features/tasks/components/AutomationForm";
import {
  useAutomation,
  useDeleteTaskAutomation,
  useRunTaskAutomation,
  useUpdateTaskAutomation,
} from "@/features/tasks/hooks/useAutomations";
import { useTask } from "@/features/tasks/hooks/useTasks";
import { parseSkillTemplateId } from "@/features/tasks/skills/skillTemplateIds";
import { useThemeColors } from "@/lib/theme";

export default function AutomationDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const themeColors = useThemeColors();
  const { data: automation, isLoading, error } = useAutomation(id);
  const { data: lastTask } = useTask(automation?.last_task_id ?? "");
  const updateAutomation = useUpdateTaskAutomation();
  const deleteAutomation = useDeleteTaskAutomation();
  const runAutomation = useRunTaskAutomation();
  const [isEditing, setIsEditing] = useState(false);
  const [fieldError, setFieldError] = useState<{
    attr: string | null;
    message: string | null;
  } | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const repositoryRequired = automation
    ? parseSkillTemplateId(automation.template_id) !== null ||
      automation.repository.trim().length > 0
    : true;

  if (error || (!automation && !isLoading)) {
    return (
      <>
        <Stack.Screen
          options={{
            headerShown: true,
            headerTitle: "Automation",
            headerStyle: { backgroundColor: themeColors.background },
            headerTintColor: themeColors.gray[12],
            presentation: "modal",
          }}
        />
        <View className="flex-1 items-center justify-center bg-background px-4">
          <Text className="mb-4 text-center text-status-error">
            {error?.message ?? "Automation not found"}
          </Text>
          <Pressable
            onPress={() => router.back()}
            className="rounded-lg bg-gray-3 px-4 py-2"
          >
            <Text className="text-gray-12">Go back</Text>
          </Pressable>
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerTitle: isEditing
            ? "Edit automation"
            : (automation?.name ?? "Automation"),
          headerStyle: { backgroundColor: themeColors.background },
          headerTintColor: themeColors.gray[12],
          presentation: "modal",
        }}
      />
      <KeyboardAvoidingView
        className="flex-1 bg-background"
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={90}
      >
        <ScrollView
          className="flex-1 px-3 pt-4"
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingBottom: 40 }}
        >
          {isLoading || !automation ? (
            <View className="items-center pt-12">
              <ActivityIndicator size="large" color={themeColors.accent[9]} />
              <Text className="mt-4 text-gray-11">Loading automation...</Text>
            </View>
          ) : isEditing ? (
            <AutomationForm
              initialValues={{
                name: automation.name,
                prompt: automation.prompt,
                repositorySelection: {
                  integrationId: automation.github_integration ?? null,
                  repository: automation.repository || null,
                },
                cronExpression: automation.cron_expression,
                timezone: automation.timezone ?? "UTC",
                enabled: automation.enabled,
              }}
              isSubmitting={updateAutomation.isPending}
              submitLabel="Save changes"
              fieldError={fieldError}
              generalError={generalError}
              repositoryRequired={repositoryRequired}
              onCancel={() => {
                setFieldError(null);
                setGeneralError(null);
                setIsEditing(false);
              }}
              onSubmit={async (values) => {
                setFieldError(null);
                setGeneralError(null);

                try {
                  await updateAutomation.mutateAsync({
                    automationId: automation.id,
                    updates: {
                      ...values,
                      template_id: automation.template_id ?? null,
                    },
                  });
                  setIsEditing(false);
                } catch (error) {
                  if (error instanceof TaskAutomationValidationError) {
                    setFieldError({
                      attr: error.attr,
                      message: error.message,
                    });
                    return;
                  }

                  setGeneralError("Could not save automation changes.");
                }
              }}
            />
          ) : (
            <AutomationDetail
              automation={automation}
              lastTaskRunStatus={lastTask?.latest_run?.status ?? null}
              isWorking={runAutomation.isPending || updateAutomation.isPending}
              onEdit={() => setIsEditing(true)}
              onToggleEnabled={async () => {
                setFieldError(null);
                setGeneralError(null);
                try {
                  await updateAutomation.mutateAsync({
                    automationId: automation.id,
                    updates: {
                      enabled: !automation.enabled,
                    },
                  });
                } catch {
                  setGeneralError("Could not update automation state.");
                }
              }}
              onRunNow={async () => {
                setFieldError(null);
                setGeneralError(null);
                try {
                  const updatedAutomation = await runAutomation.mutateAsync(
                    automation.id,
                  );
                  if (updatedAutomation.last_task_id) {
                    router.push({
                      pathname: "/task/[id]",
                      params: {
                        id: updatedAutomation.last_task_id,
                        fromAutomation: "1",
                        automationName: updatedAutomation.name,
                      },
                    });
                  }
                } catch {
                  setGeneralError("Could not start the automation run.");
                }
              }}
              onDelete={() => {
                Alert.alert(
                  "Delete automation?",
                  "This will remove the schedule and stop future runs.",
                  [
                    {
                      text: "Cancel",
                      style: "cancel",
                    },
                    {
                      text: "Delete",
                      style: "destructive",
                      onPress: async () => {
                        try {
                          await deleteAutomation.mutateAsync(automation.id);
                          router.back();
                        } catch {
                          setGeneralError("Could not delete automation.");
                        }
                      },
                    },
                  ],
                );
              }}
            />
          )}

          {generalError && !isEditing && (
            <Text className="mt-4 text-sm text-status-error">
              {generalError}
            </Text>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}
