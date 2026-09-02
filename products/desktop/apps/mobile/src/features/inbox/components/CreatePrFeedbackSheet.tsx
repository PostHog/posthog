import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import { Play, Plus } from "phosphor-react-native";
import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { useThemeColors } from "@/lib/theme";

interface CreatePrFeedbackSheetProps {
  visible: boolean;
  isAwaitingInput: boolean;
  onClose: () => void;
  onSubmit: (feedback: string) => void;
}

export function CreatePrFeedbackSheet({
  visible,
  isAwaitingInput,
  onClose,
  onSubmit,
}: CreatePrFeedbackSheetProps) {
  const themeColors = useThemeColors();
  const [feedback, setFeedback] = useState("");
  const [prevVisible, setPrevVisible] = useState(visible);
  const confirmLabel = isAwaitingInput ? "Implement as new task" : "Start task";

  // Reset the draft when the sheet opens. Adjusting during render (rather than
  // in an effect) avoids a flash of the previous value on the next open.
  if (visible !== prevVisible) {
    setPrevVisible(visible);
    if (visible) setFeedback("");
  }

  const handleSubmit = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onSubmit(feedback.trim());
  };

  return (
    <SheetContainer open={visible} onClose={onClose} bottomGap="default">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View className="px-4 pt-2 pb-3">
          <Text className="mb-1 font-semibold text-[16px] text-gray-12">
            Add feedback
          </Text>
          <Text className="mb-3 text-[13px] text-gray-11 leading-snug">
            Optional. The agent takes this into account, including any questions
            raised in the report thread.
          </Text>
          <TextInput
            value={feedback}
            onChangeText={setFeedback}
            placeholder="Add any extra feedback, e.g. answers to questions raised in the report thread..."
            placeholderTextColor={themeColors.gray[9]}
            multiline
            maxLength={2000}
            autoFocus
            className="min-h-[96px] rounded-xl bg-gray-2 px-3 py-3 text-[14px] text-gray-12"
            style={{ textAlignVertical: "top" }}
          />
          <View className="mt-3 flex-row items-center justify-end gap-2">
            <Pressable
              onPress={onClose}
              hitSlop={6}
              className="rounded-full px-4 py-2.5 active:opacity-60"
            >
              <Text className="text-[14px] text-gray-11">Cancel</Text>
            </Pressable>
            <Pressable
              onPress={handleSubmit}
              accessibilityRole="button"
              accessibilityLabel={confirmLabel}
              className="flex-row items-center gap-1.5 rounded-full bg-accent-9 px-4 py-2.5 active:opacity-80"
            >
              {isAwaitingInput ? (
                <Plus size={16} color="#ffffff" weight="bold" />
              ) : (
                <Play size={16} color="#ffffff" weight="fill" />
              )}
              <Text className="font-semibold text-[14px] text-white">
                {confirmLabel}
              </Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SheetContainer>
  );
}
