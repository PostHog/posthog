import { getCalendars } from "expo-localization";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { Text } from "@/components/text";
import { TaskAutomationValidationError } from "@/features/tasks/api";
import { AutomationForm } from "@/features/tasks/components/AutomationForm";
import { useCreateTaskAutomation } from "@/features/tasks/hooks/useAutomations";
import { useSkillStoreSkill } from "@/features/tasks/skills/hooks";
import { formatSkillTemplateId } from "@/features/tasks/skills/skillTemplateIds";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

// Reserved space below the scrolling form content. Tall enough that the
// floating Create button never covers the prompt editor's tail — the
// user can scroll the very last line of the prompt up above the button.
// Composed of the button's own area + safe-area inset at the bottom of
// the screen.
const FLOATING_BUTTON_AREA_HEIGHT = 64;
const FLOATING_BUTTON_DEAD_SPACE = 32;

export default function CreateAutomationScreen() {
  const { skillName: skillNameParam } = useLocalSearchParams<{
    skillName?: string | string[];
  }>();
  const skillName = Array.isArray(skillNameParam)
    ? skillNameParam[0]
    : skillNameParam;
  const router = useRouter();
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const createAutomation = useCreateTaskAutomation();
  const defaultTimezone = useMemo(
    () => getCalendars()[0]?.timeZone ?? "UTC",
    [],
  );
  const selectedSkill = useSkillStoreSkill(skillName ?? null);
  const selectedSkillName = selectedSkill.data?.name ?? skillName ?? null;
  const skillInitialValues = useMemo(
    () =>
      selectedSkill.data && selectedSkillName
        ? {
            name: selectedSkill.data.name,
            prompt: selectedSkill.data.body,
            enabled: true,
            template_id: formatSkillTemplateId(selectedSkillName),
          }
        : null,
    [selectedSkill.data, selectedSkillName],
  );
  const [fieldError, setFieldError] = useState<{
    attr: string | null;
    message: string | null;
  } | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);

  // Bridge to the form's internal submit handler so the floating button
  // — rendered outside the form's tree — can trigger validation+submit.
  // Mirrored `canSubmit` lets us disable the button in lockstep with form
  // validity without lifting all of the form's state up to the screen.
  const submitRef = useRef<(() => void) | null>(null);
  const [canSubmit, setCanSubmit] = useState(false);
  const isSubmitting = createAutomation.isPending;

  // Whether the form is even mounted yet — controls whether the floating
  // button is shown. While the skill is still loading or failed to load,
  // the form isn't on screen, so there's nothing to submit.
  const formMounted =
    !skillName || (!selectedSkill.isPending && !!selectedSkill.data);

  // Dead space at the bottom of the scroll content so the floating button
  // can sit over a region with no form content. When the user scrolls to
  // the very end of the prompt editor, the last line clears above the
  // button instead of being hidden behind it.
  const scrollPaddingBottom =
    FLOATING_BUTTON_AREA_HEIGHT + insets.bottom + FLOATING_BUTTON_DEAD_SPACE;

  const handleCreate = () => submitRef.current?.();

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerTitle: "Create automation",
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
          className="flex-1 px-4 pt-4"
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingBottom: scrollPaddingBottom }}
        >
          <View className="gap-4">
            {skillName && selectedSkill.isPending ? (
              <View className="items-center rounded-xl border border-gray-6 bg-gray-2 p-5">
                <ActivityIndicator size="small" color={themeColors.accent[9]} />
                <Text className="mt-3 text-gray-11 text-sm">
                  Loading the selected skill...
                </Text>
              </View>
            ) : skillName && (selectedSkill.error || !selectedSkill.data) ? (
              <View className="rounded-xl border border-gray-6 bg-gray-2 p-4">
                <Text className="font-semibold text-[15px] text-gray-12">
                  Could not load this skill
                </Text>
                <Text className="mt-2 text-gray-11 text-sm">
                  {selectedSkill.error?.message ??
                    "The selected skill is unavailable right now."}
                </Text>
                <View className="mt-4 flex-row gap-3">
                  <Pressable
                    onPress={() => void selectedSkill.refetch()}
                    className="flex-1 rounded-xl border border-gray-6 bg-gray-1 py-3"
                  >
                    <Text className="text-center font-medium text-gray-12">
                      Try again
                    </Text>
                  </Pressable>
                  <Pressable
                    onPress={() => router.replace("/automation/create")}
                    className="flex-1 rounded-xl border border-gray-6 bg-gray-1 py-3"
                  >
                    <Text className="text-center font-medium text-gray-12">
                      Start from scratch
                    </Text>
                  </Pressable>
                </View>
              </View>
            ) : (
              <>
                {selectedSkillName && (
                  <View>
                    <Text className="text-[11px] text-gray-9 uppercase">
                      Skill
                    </Text>
                    <Text className="mt-1 font-semibold text-[16px] text-gray-12">
                      {selectedSkillName}
                    </Text>
                  </View>
                )}

                <AutomationForm
                  initialValues={{
                    name: skillInitialValues?.name,
                    prompt: skillInitialValues?.prompt,
                    timezone: defaultTimezone,
                    enabled: skillInitialValues?.enabled ?? true,
                  }}
                  initialPromptMode={selectedSkillName ? "preview" : "edit"}
                  isSubmitting={isSubmitting}
                  submitLabel="Create"
                  fieldError={fieldError}
                  generalError={generalError}
                  // Footer is rendered by the screen as a floating button.
                  hideFooter
                  submitRef={submitRef}
                  onCanSubmitChange={setCanSubmit}
                  onSubmit={async (values) => {
                    setFieldError(null);
                    setGeneralError(null);

                    try {
                      const automation = await createAutomation.mutateAsync({
                        ...values,
                        template_id: skillInitialValues?.template_id ?? null,
                      });
                      router.replace(`/automation/${automation.id}`);
                    } catch (error) {
                      if (error instanceof TaskAutomationValidationError) {
                        setFieldError({
                          attr: error.attr,
                          message: error.message,
                        });
                        return;
                      }

                      setGeneralError(
                        "Could not create automation. Please try again.",
                      );
                    }
                  }}
                />
              </>
            )}
          </View>
        </ScrollView>

        {/* Floating Create button — sits inside the KeyboardAvoidingView
            so it rises with the keyboard, but outside the ScrollView so
            it stays anchored to the bottom of the screen regardless of
            how far the user has scrolled. The ScrollView's bottom padding
            (above) reserves enough dead space that the prompt editor's
            last line can always be scrolled clear of this button. */}
        {formMounted && (
          <View
            className="absolute inset-x-0 bottom-0 border-gray-6 border-t bg-background px-4 pt-3"
            style={{ paddingBottom: bottom("compact") }}
          >
            <Pressable
              onPress={handleCreate}
              disabled={!canSubmit || isSubmitting}
              accessibilityRole="button"
              accessibilityLabel="Create automation"
              className={`rounded-xl py-3.5 ${
                canSubmit && !isSubmitting ? "bg-accent-9" : "bg-gray-3"
              }`}
            >
              {isSubmitting ? (
                <ActivityIndicator
                  size="small"
                  color={themeColors.accent.contrast}
                />
              ) : (
                <Text
                  className={`text-center font-semibold text-[15px] ${
                    canSubmit ? "text-accent-contrast" : "text-gray-9"
                  }`}
                >
                  Create
                </Text>
              )}
            </Pressable>
          </View>
        )}
      </KeyboardAvoidingView>
    </>
  );
}
