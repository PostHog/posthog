import * as Haptics from "expo-haptics";
import { BookOpen } from "phosphor-react-native";
import { Alert, Pressable } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useSkillsAvailable } from "../skills/hooks";
import { buildCreateSkillFromTaskPrompt } from "../skills/skillFromTaskPrompt";

interface CreateSkillFromTaskButtonProps {
  taskTitle?: string | null;
  /**
   * False while a turn is in flight — the same gate the composer uses. The
   * action sends a prompt, so it has to wait its turn like any other message.
   */
  canSend: boolean;
  onSend: (prompt: string) => void;
}

/**
 * Asks the agent to distill the current conversation into a reusable team
 * skill, by sending a prompt into this task's own session. Hidden when the
 * project has no skills feature, since the tool call would just fail.
 */
export function CreateSkillFromTaskButton({
  taskTitle,
  canSend,
  onSend,
}: CreateSkillFromTaskButtonProps) {
  const themeColors = useThemeColors();
  const skillsAvailable = useSkillsAvailable();

  if (!skillsAvailable || !canSend) return null;

  const confirm = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    Alert.alert(
      "Create skill from task",
      "The agent will distill this conversation into a reusable team skill and save it to your skill store.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Create",
          onPress: () => onSend(buildCreateSkillFromTaskPrompt({ taskTitle })),
        },
      ],
    );
  };

  return (
    <Pressable
      onPress={confirm}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel="Create skill from task"
      className="h-8 w-8 items-center justify-center rounded-lg active:bg-gray-3"
    >
      <BookOpen size={18} color={themeColors.gray[11]} />
    </Pressable>
  );
}
