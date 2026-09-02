import { Text } from "@components/text";
import { buildDiscussReportPrompt } from "@posthog/shared";
import * as Haptics from "expo-haptics";
import { ChatCircle } from "phosphor-react-native";
import { useEffect, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { inboxReportShareUrl } from "@/lib/deep-links";
import { useThemeColors } from "@/lib/theme";

interface DiscussReportSheetProps {
  visible: boolean;
  reportId: string;
  reportTitle?: string | null;
  onClose: () => void;
  onSubmit: (params: { prompt: string; question: string }) => void;
}

export function DiscussReportSheet({
  visible,
  reportId,
  reportTitle,
  onClose,
  onSubmit,
}: DiscussReportSheetProps) {
  const themeColors = useThemeColors();
  const [question, setQuestion] = useState("");

  useEffect(() => {
    if (visible) setQuestion("");
  }, [visible]);

  const handleSubmit = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const trimmed = question.trim();
    const reportLink = inboxReportShareUrl(reportId, reportTitle);
    const prompt = buildDiscussReportPrompt({
      reportId,
      reportLink,
      question: trimmed || undefined,
    });
    onSubmit({ prompt, question: trimmed });
  };

  return (
    <SheetContainer open={visible} onClose={onClose} bottomGap="default">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View className="px-4 pt-2 pb-3">
          <Text className="mb-1 font-semibold text-[16px] text-gray-12">
            Discuss this report
          </Text>
          <Text className="mb-3 text-[13px] text-gray-11 leading-snug">
            Ask a question, or leave it blank for a brief readout from the
            agent.
          </Text>
          <TextInput
            value={question}
            onChangeText={setQuestion}
            placeholder="What do you want to know?"
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
              accessibilityLabel="Start discussion"
              className="flex-row items-center gap-1.5 rounded-full bg-accent-9 px-4 py-2.5 active:opacity-80"
            >
              <ChatCircle size={16} color="#ffffff" weight="fill" />
              <Text className="font-semibold text-[14px] text-white">
                Discuss
              </Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SheetContainer>
  );
}
