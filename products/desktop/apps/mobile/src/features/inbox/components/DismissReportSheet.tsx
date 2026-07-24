import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import { Check } from "phosphor-react-native";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";
import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
} from "../constants";
import { useDismissReport } from "../hooks/useInboxReports";

export interface DismissReportResult {
  reason: DismissalReasonOptionValue;
  /** Trimmed note text the user provided, if any. Empty/whitespace-only notes become null. */
  note: string | null;
}

interface DismissReportSheetProps {
  visible: boolean;
  reportId: string;
  reportTitle: string;
  onClose: () => void;
  /**
   * Fires after the API confirms the dismissal. The result is passed back so
   * callers can route the reason/note through their own analytics — keeping
   * this sheet stateless about the surface it was launched from.
   */
  onDismissed: (result: DismissReportResult) => void;
}

export function DismissReportSheet({
  visible,
  reportId,
  reportTitle,
  onClose,
  onDismissed,
}: DismissReportSheetProps) {
  const { insets, bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const [reason, setReason] = useState<DismissalReasonOptionValue | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const dismiss = useDismissReport(reportId);

  useEffect(() => {
    if (visible) {
      setReason(null);
      setNote("");
      setError(null);
    }
  }, [visible]);

  const handleConfirm = async () => {
    if (!reason || dismiss.isPending) return;
    setError(null);
    const trimmedNote = note.trim();
    try {
      await dismiss.mutateAsync({
        reason,
        note: trimmedNote || undefined,
      });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      onDismissed({ reason, note: trimmedNote || null });
    } catch (err) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(
        err instanceof Error
          ? err.message
          : "Could not dismiss this report. Please try again.",
      );
    }
  };

  const canSubmit = !!reason && !dismiss.isPending;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        className="flex-1 bg-background"
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={0}
      >
        <View
          className="flex-1 bg-background"
          style={{ paddingTop: sheetContentTop() }}
        >
          {/* Header */}
          <View className="flex-row items-center justify-between border-gray-6 border-b px-4 pb-3">
            <Text className="font-semibold text-[18px] text-gray-12">
              Dismiss report
            </Text>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              disabled={dismiss.isPending}
            >
              <Text className="text-[14px] text-accent-9">Cancel</Text>
            </Pressable>
          </View>

          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingTop: 16,
              paddingBottom: insets.bottom + 120,
            }}
          >
            <Text className="text-[13px] text-gray-11 leading-snug">
              {`This will remove "${reportTitle}" from your inbox. Your feedback is saved on the report and helps the agent.`}
            </Text>

            <Text className="mt-5 mb-2 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
              Reason
            </Text>
            <View className="overflow-hidden rounded-xl bg-gray-2">
              {DISMISSAL_REASON_OPTIONS.map((option, idx) => {
                const selected = reason === option.value;
                return (
                  <Pressable
                    key={option.value}
                    onPress={() => setReason(option.value)}
                    hitSlop={4}
                    className={`flex-row items-center justify-between px-3 py-3.5 active:bg-gray-3 ${
                      idx > 0 ? "border-gray-5 border-t" : ""
                    }`}
                  >
                    <Text className="flex-1 pr-3 text-[14px] text-gray-12">
                      {option.label}
                    </Text>
                    {selected && (
                      <Check size={16} color={themeColors.accent[9]} />
                    )}
                  </Pressable>
                );
              })}
            </View>

            <Text className="mt-5 mb-2 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
              Note (optional)
            </Text>
            <TextInput
              value={note}
              onChangeText={setNote}
              placeholder="Add detail so the agent can learn"
              placeholderTextColor={themeColors.gray[9]}
              multiline
              numberOfLines={3}
              maxLength={4000}
              editable={!dismiss.isPending}
              className="min-h-[88px] rounded-xl bg-gray-2 px-3 py-3 text-[14px] text-gray-12"
              style={{ textAlignVertical: "top" }}
            />

            {error && (
              <Text className="mt-3 text-[13px] text-status-error">
                {error}
              </Text>
            )}
          </ScrollView>

          {/* Sticky submit */}
          <View
            className="border-gray-6 border-t bg-background px-4 pt-3"
            style={{ paddingBottom: bottom("compact") }}
          >
            <Pressable
              onPress={handleConfirm}
              disabled={!canSubmit}
              className={`flex-row items-center justify-center rounded-full px-6 py-3.5 ${
                canSubmit ? "bg-accent-9 active:opacity-80" : "bg-gray-4"
              }`}
            >
              {dismiss.isPending ? (
                <ActivityIndicator color={themeColors.gray[12]} />
              ) : (
                <Text
                  className={`font-semibold text-[15px] ${
                    canSubmit ? "text-gray-12" : "text-gray-9"
                  }`}
                >
                  Dismiss & teach the agent
                </Text>
              )}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
