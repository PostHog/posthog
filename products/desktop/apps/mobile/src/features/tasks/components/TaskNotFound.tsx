import { Text } from "@components/text";
import { MagnifyingGlass } from "phosphor-react-native";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { FloatingBackButton } from "@/components/FloatingBackButton";
import { ProjectSelectSheet } from "@/features/auth";
import { useThemeColors } from "@/lib/theme";

interface TaskNotFoundProps {
  onGoBack: () => void;
}

/**
 * The task id resolved to a 404. That is nearly always a cross-project link —
 * a push, a shared URL, or a project switch — so the primary action is the
 * project picker rather than a retry, which would just 404 again.
 */
export function TaskNotFound({ onGoBack }: TaskNotFoundProps) {
  const themeColors = useThemeColors();
  const [projectSheetOpen, setProjectSheetOpen] = useState(false);

  return (
    <View className="flex-1 items-center justify-center bg-background px-8">
      <FloatingBackButton />

      <View className="mb-4 h-12 w-12 items-center justify-center rounded-full bg-gray-3">
        <MagnifyingGlass size={22} color={themeColors.gray[11]} weight="bold" />
      </View>

      <Text className="mb-1 text-center font-semibold text-[18px] text-gray-12">
        Task not found
      </Text>
      <Text className="mb-6 text-center text-[14px] text-gray-10 leading-snug">
        It may live in a different project, or it may have been deleted.
      </Text>

      <View className="w-full gap-2">
        <Pressable
          onPress={() => setProjectSheetOpen(true)}
          className="items-center rounded-lg bg-accent-9 px-4 py-3 active:opacity-80"
          accessibilityRole="button"
        >
          <Text className="font-semibold text-[15px] text-accent-contrast">
            Switch project
          </Text>
        </Pressable>
        <Pressable
          onPress={onGoBack}
          className="items-center rounded-lg border border-gray-5 px-4 py-3 active:bg-gray-2"
          accessibilityRole="button"
        >
          <Text className="font-medium text-[15px] text-gray-12">Go back</Text>
        </Pressable>
      </View>

      {/* Switching re-runs the task load against the newly active project, so
          the screen recovers in place instead of bouncing the user out. */}
      <ProjectSelectSheet
        open={projectSheetOpen}
        title="Switch project"
        onClose={() => setProjectSheetOpen(false)}
      />
    </View>
  );
}
