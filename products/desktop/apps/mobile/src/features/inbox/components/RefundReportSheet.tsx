import { Text } from "@components/text";
import { REFUND_REASON_OPTIONS } from "@posthog/shared";
import type { SignalReportRefundReason } from "@posthog/shared/domain-types";
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
import { useRefundReport } from "../hooks/useInboxReports";

interface RefundReportSheetProps {
  visible: boolean;
  reportId: string;
  reportTitle: string;
  onClose: () => void;
  onRefunded: () => void;
}

export function RefundReportSheet({
  visible,
  reportId,
  reportTitle,
  onClose,
  onRefunded,
}: RefundReportSheetProps) {
  const { insets, bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const [reason, setReason] = useState<SignalReportRefundReason | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const refund = useRefundReport(reportId);

  useEffect(() => {
    if (visible) {
      setReason(null);
      setNote("");
      setError(null);
    }
  }, [visible]);

  const handleConfirm = async () => {
    if (!reason || refund.isPending) return;
    setError(null);
    const trimmedNote = note.trim();
    try {
      await refund.mutateAsync({
        reason,
        note: trimmedNote || undefined,
      });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      onRefunded();
    } catch (err) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(err instanceof Error ? err.message : "Couldn't refund this PR.");
    }
  };

  const canSubmit = !!reason && !refund.isPending;

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
          <View className="flex-row items-center justify-between border-gray-6 border-b px-4 pb-3">
            <Text className="font-semibold text-[18px] text-gray-12">
              Refund PR
            </Text>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              disabled={refund.isPending}
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
              {`You won't pay for the PR on "${reportTitle}" and it won't count toward your included PRs. The report is archived as part of the refund and can't be restored.`}
            </Text>

            <Text className="mt-5 mb-2 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
              Reason
            </Text>
            <View className="overflow-hidden rounded-xl bg-gray-2">
              {REFUND_REASON_OPTIONS.map((option, idx) => {
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
              placeholder="Helps us review refunds"
              placeholderTextColor={themeColors.gray[9]}
              multiline
              numberOfLines={3}
              maxLength={4000}
              editable={!refund.isPending}
              className="min-h-[88px] rounded-xl bg-gray-2 px-3 py-3 text-[14px] text-gray-12"
              style={{ textAlignVertical: "top" }}
            />

            {error && (
              <Text className="mt-3 text-[13px] text-status-error">
                {error}
              </Text>
            )}
          </ScrollView>

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
              {refund.isPending ? (
                <ActivityIndicator color={themeColors.gray[12]} />
              ) : (
                <Text
                  className={`font-semibold text-[15px] ${
                    canSubmit ? "text-gray-12" : "text-gray-9"
                  }`}
                >
                  Refund PR
                </Text>
              )}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
