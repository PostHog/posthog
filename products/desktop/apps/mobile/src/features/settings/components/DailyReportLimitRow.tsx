import { Text } from "@components/text";
import {
  dailyReportLimitFieldValue,
  describeDailyReportLimit,
  parseDailyReportLimit,
} from "@posthog/core/inbox/dailyReportLimit";
import { CaretRight } from "phosphor-react-native";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import {
  useSignalTeamConfig,
  useUpdateMaxReportsPerDay,
} from "@/features/inbox/hooks/useSignalTeamConfig";
import { useThemeColors } from "@/lib/theme";

export function DailyReportLimitRow() {
  const themeColors = useThemeColors();
  const { data: config, isLoading, isError } = useSignalTeamConfig();
  const updateLimit = useUpdateMaxReportsPerDay();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const status = describeDailyReportLimit(config);
  const savedValue = dailyReportLimitFieldValue(config);
  // A failed background refetch keeps the cached config while flipping isError,
  // so only treat the case with no cached config as a hard error. Otherwise a
  // transient failure would hide a known cap and block editing a value the user
  // can still read from cache.
  const showLoadError = isError && config === undefined;
  const rightLabel = showLoadError
    ? "—"
    : status.limit === null
      ? "No limit"
      : String(status.limit);

  // Reset the field from the saved value when the sheet opens (an event, not a
  // prop-sync effect).
  const openSheet = () => {
    setDraft(savedValue);
    setError(null);
    setSheetOpen(true);
  };

  const save = async (limit: number | null) => {
    setError(null);
    try {
      await updateLimit.mutateAsync(limit);
      setSheetOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save the limit.");
    }
  };

  const handleSave = () => {
    const parsed = parseDailyReportLimit(draft);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    void save(parsed.value);
  };

  return (
    <>
      <Pressable
        onPress={openSheet}
        disabled={isLoading || showLoadError}
        className={`active:bg-gray-2 ${isLoading || showLoadError ? "opacity-50" : ""}`}
      >
        <View className="flex-row items-center gap-3 border-gray-5 border-b px-4 py-3">
          <View className="min-w-0 flex-1">
            <Text className="font-medium text-[15px] text-gray-12">
              Daily report limit
            </Text>
            <Text
              className={`mt-0.5 text-[12px] leading-snug ${showLoadError ? "text-status-error" : "text-gray-10"}`}
            >
              {showLoadError
                ? "Couldn't load the limit. Try again later."
                : status.usageText}
            </Text>
            {!showLoadError && status.reachedText ? (
              <Text className="mt-0.5 text-[12px] text-status-warning leading-snug">
                {status.reachedText}
              </Text>
            ) : null}
          </View>
          <View className="shrink-0 flex-row items-center gap-2">
            <Text className="text-[14px] text-gray-11">{rightLabel}</Text>
            <CaretRight size={14} color={themeColors.gray[10]} />
          </View>
        </View>
      </Pressable>

      <DailyReportLimitSheet
        open={sheetOpen}
        draft={draft}
        error={error}
        isSaving={updateLimit.isPending}
        hasSavedValue={savedValue !== ""}
        onChangeDraft={(text) => {
          setDraft(text);
          setError(null);
        }}
        onClose={() => setSheetOpen(false)}
        onSave={handleSave}
        onClear={() => void save(null)}
      />
    </>
  );
}

interface DailyReportLimitSheetProps {
  open: boolean;
  draft: string;
  error: string | null;
  isSaving: boolean;
  hasSavedValue: boolean;
  onChangeDraft: (text: string) => void;
  onClose: () => void;
  onSave: () => void;
  onClear: () => void;
}

function DailyReportLimitSheet({
  open,
  draft,
  error,
  isSaving,
  hasSavedValue,
  onChangeDraft,
  onClose,
  onSave,
  onClear,
}: DailyReportLimitSheetProps) {
  const themeColors = useThemeColors();

  return (
    <SheetContainer open={open} onClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View className="gap-3 px-4 pt-2 pb-2">
          <Text className="font-semibold text-[16px] text-gray-12">
            Daily report limit
          </Text>
          <Text className="text-[13px] text-gray-10 leading-snug">
            Cap how many new reports reach the inbox each day. Leave the field
            empty for no limit.
          </Text>

          <TextInput
            value={draft}
            onChangeText={onChangeDraft}
            keyboardType="number-pad"
            placeholder="No limit"
            placeholderTextColor={themeColors.gray[9]}
            editable={!isSaving}
            className="rounded-lg border border-gray-6 bg-gray-2 px-3 py-2.5 text-[15px] text-gray-12"
          />

          {error ? (
            <Text className="text-[12.5px] text-status-error">{error}</Text>
          ) : null}

          <View className="flex-row gap-2">
            <Pressable
              onPress={onSave}
              disabled={isSaving}
              className={`flex-1 flex-row items-center justify-center rounded-lg bg-accent-9 py-3 ${isSaving ? "opacity-60" : "active:opacity-80"}`}
            >
              {isSaving ? (
                <ActivityIndicator size="small" color={themeColors.gray[1]} />
              ) : (
                <Text className="font-semibold text-[15px] text-gray-1">
                  Save
                </Text>
              )}
            </Pressable>
            {hasSavedValue ? (
              <Pressable
                onPress={onClear}
                disabled={isSaving}
                className={`flex-row items-center justify-center rounded-lg border border-gray-6 px-4 py-3 ${isSaving ? "opacity-60" : "active:bg-gray-2"}`}
              >
                <Text className="font-semibold text-[15px] text-gray-12">
                  Clear
                </Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      </KeyboardAvoidingView>
    </SheetContainer>
  );
}
