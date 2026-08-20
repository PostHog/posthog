import { Text } from "@components/text";
import {
  dailyReportLimitFieldValue,
  describeDailyReportLimit,
  parseDailyReportLimit,
} from "@posthog/core/inbox/dailyReportLimit";
import { CaretRight } from "phosphor-react-native";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import {
  useSignalTeamConfig,
  useUpdateMaxReportsPerDay,
} from "@/features/inbox/hooks/useSignalTeamConfig";
import { useThemeColors } from "@/lib/theme";

export function DailyReportLimitRow() {
  const themeColors = useThemeColors();
  const { data: config, isLoading } = useSignalTeamConfig();
  const updateLimit = useUpdateMaxReportsPerDay();
  const [sheetOpen, setSheetOpen] = useState(false);

  const status = describeDailyReportLimit(config);
  const rightLabel = status.limit === null ? "No limit" : String(status.limit);

  return (
    <>
      <Pressable
        onPress={() => setSheetOpen(true)}
        disabled={isLoading}
        className={`active:bg-gray-2 ${isLoading ? "opacity-50" : ""}`}
      >
        <View className="flex-row items-center gap-3 border-gray-5 border-b px-4 py-3">
          <View className="min-w-0 flex-1">
            <Text className="font-medium text-[15px] text-gray-12">
              Daily report limit
            </Text>
            <Text className="mt-0.5 text-[12px] text-gray-10 leading-snug">
              {status.usageText}
            </Text>
            {status.reachedText ? (
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
        initialValue={dailyReportLimitFieldValue(config)}
        isSaving={updateLimit.isPending}
        onClose={() => setSheetOpen(false)}
        onSave={async (limit) => {
          await updateLimit.mutateAsync(limit);
          setSheetOpen(false);
        }}
      />
    </>
  );
}

interface DailyReportLimitSheetProps {
  open: boolean;
  initialValue: string;
  isSaving: boolean;
  onClose: () => void;
  onSave: (limit: number | null) => Promise<void>;
}

function DailyReportLimitSheet({
  open,
  initialValue,
  isSaving,
  onClose,
  onSave,
}: DailyReportLimitSheetProps) {
  const themeColors = useThemeColors();
  const [draft, setDraft] = useState(initialValue);
  const [error, setError] = useState<string | null>(null);

  // Reset the field to the saved value each time the sheet opens.
  useEffect(() => {
    if (open) {
      setDraft(initialValue);
      setError(null);
    }
  }, [open, initialValue]);

  const submit = async (limit: number | null) => {
    setError(null);
    try {
      await onSave(limit);
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
    void submit(parsed.value);
  };

  return (
    <SheetContainer open={open} onClose={onClose}>
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
          onChangeText={(text) => {
            setDraft(text);
            setError(null);
          }}
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
            onPress={handleSave}
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
          {initialValue !== "" ? (
            <Pressable
              onPress={() => void submit(null)}
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
    </SheetContainer>
  );
}
