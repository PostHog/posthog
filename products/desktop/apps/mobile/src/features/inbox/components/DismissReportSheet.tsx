import { Text } from "@components/text";
import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  isDismissalReasonSnooze,
} from "@posthog/shared";
import * as Haptics from "expo-haptics";
import { Check } from "phosphor-react-native";
import { useEffect, useRef, useState } from "react";
import {
  Alert,
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
import { useDismissReport } from "../hooks/useInboxReports";
import { useDismissDraftStore } from "../stores/dismissDraftStore";

export interface DismissReportResult {
  reason: DismissalReasonOptionValue;
  /** Trimmed note text the user provided, if any. Empty/whitespace-only notes become null. */
  note: string | null;
}

const PAUSE_OPTIONS = DISMISSAL_REASON_OPTIONS.filter((option) =>
  isDismissalReasonSnooze(option.value),
);
const HIDE_OPTIONS = DISMISSAL_REASON_OPTIONS.filter(
  (option) => !isDismissalReasonSnooze(option.value),
);

interface DismissReportSheetProps {
  visible: boolean;
  reportId: string;
  reportTitle: string;
  hasOpenPr?: boolean;
  onClose: () => void;
  /** Fires the moment the user confirms, before the API write settles. */
  onDismissed: (result: DismissReportResult) => void;
}

export function DismissReportSheet({
  visible,
  reportId,
  reportTitle,
  hasOpenPr = false,
  onClose,
  onDismissed,
}: DismissReportSheetProps) {
  const { insets, bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const draft = useDismissDraftStore((s) => s.drafts[reportId]);
  const setDraft = useDismissDraftStore((s) => s.setDraft);
  const [reason, setReason] = useState<DismissalReasonOptionValue | null>(null);
  const [note, setNote] = useState("");
  const dismiss = useDismissReport(reportId);

  const sheetVisible = visible || draft?.reopen === true;
  const openTransitionRef = useRef(false);

  useEffect(() => {
    if (!sheetVisible) {
      openTransitionRef.current = false;
      return;
    }
    if (openTransitionRef.current) return;
    openTransitionRef.current = true;
    if (draft?.reopen) {
      setReason(draft.reason);
      setNote(draft.note);
    } else {
      setReason(null);
      setNote("");
    }
  }, [sheetVisible, draft]);

  const displayedError = draft?.reopen ? draft.errorMessage : undefined;

  const outcome =
    reason == null
      ? null
      : isDismissalReasonSnooze(reason)
        ? "The report comes back if another matching signal arrives."
        : `Matching signals won't surface the report again.${hasOpenPr ? " The open pull request will be closed." : ""}`;

  const handleClose = () => {
    setDraft(reportId, undefined);
    onClose();
  };

  const handleConfirm = () => {
    if (!reason) return;
    const trimmedNote = note.trim();
    const noteOrNull = trimmedNote || null;
    setDraft(reportId, { reason, note: trimmedNote, reopen: false });
    onClose();
    onDismissed({ reason, note: noteOrNull });
    // Use an independently managed promise rather than mutate()'s per-call
    // callbacks: onDismissed above can trigger navigation that unmounts this
    // sheet before the write settles, and per-call mutate callbacks are only
    // fired while the initiating component is still mounted. A plain promise
    // chain has no such dependency, so the draft is always reconciled.
    dismiss.mutateAsync({ reason, note: trimmedNote || undefined }).then(
      () => {
        setDraft(reportId, undefined);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      },
      (err) => {
        const message =
          err instanceof Error
            ? err.message
            : "Could not dismiss this report. Please try again.";
        setDraft(reportId, {
          reason,
          note: trimmedNote,
          reopen: true,
          errorMessage: message,
        });
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        Alert.alert("Couldn't dismiss report", message);
      },
    );
  };

  const canSubmit = !!reason;

  return (
    <Modal
      visible={sheetVisible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
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
              Dismiss report
            </Text>
            <Pressable onPress={handleClose} hitSlop={12}>
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

            <ReasonGroup
              heading="Pause until a new matching signal"
              options={PAUSE_OPTIONS}
              selected={reason}
              onSelect={setReason}
              accentColor={themeColors.accent[9]}
            />

            <ReasonGroup
              heading="Don't surface again"
              options={HIDE_OPTIONS}
              selected={reason}
              onSelect={setReason}
              accentColor={themeColors.accent[9]}
            />

            <Text className="mt-5 mb-2 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
              Details (optional)
            </Text>
            <TextInput
              value={note}
              onChangeText={(value) => {
                setNote(value);
                if (reason === null && value.trim()) {
                  setReason("other");
                }
              }}
              placeholder="What should the agent know?"
              placeholderTextColor={themeColors.gray[9]}
              multiline
              numberOfLines={3}
              maxLength={4000}
              className="min-h-[88px] rounded-xl bg-gray-2 px-3 py-3 text-[14px] text-gray-12"
              style={{ textAlignVertical: "top" }}
            />

            {outcome && (
              <Text
                accessibilityLiveRegion="polite"
                className="mt-3 text-[13px] text-gray-11"
              >
                {outcome}
              </Text>
            )}

            {displayedError && (
              <Text className="mt-3 text-[13px] text-status-error">
                {displayedError}
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
              accessibilityLabel="Confirm dismissal"
              className={`flex-row items-center justify-center rounded-full px-6 py-3.5 ${
                canSubmit ? "bg-accent-9 active:opacity-80" : "bg-gray-4"
              }`}
            >
              <Text
                className={`font-semibold text-[15px] ${
                  canSubmit ? "text-gray-12" : "text-gray-9"
                }`}
              >
                Dismiss & teach the agent
              </Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function ReasonGroup({
  heading,
  options,
  selected,
  onSelect,
  accentColor,
}: {
  heading: string;
  options: readonly (typeof DISMISSAL_REASON_OPTIONS)[number][];
  selected: DismissalReasonOptionValue | null;
  onSelect: (value: DismissalReasonOptionValue) => void;
  accentColor: string;
}) {
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={heading}>
      <Text className="mt-5 mb-2 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
        {heading}
      </Text>
      <View className="overflow-hidden rounded-xl bg-gray-2">
        {options.map((option, idx) => {
          const isSelected = selected === option.value;
          return (
            <Pressable
              key={option.value}
              onPress={() => onSelect(option.value)}
              accessibilityLabel={`Dismissal reason: ${option.label}`}
              accessibilityRole="radio"
              accessibilityState={{ checked: isSelected }}
              hitSlop={4}
              className={`flex-row items-center justify-between px-3 py-3.5 active:bg-gray-3 ${
                idx > 0 ? "border-gray-5 border-t" : ""
              }`}
            >
              <Text className="flex-1 pr-3 text-[14px] text-gray-12">
                {option.label}
              </Text>
              {isSelected && <Check size={16} color={accentColor} />}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
