import { Text } from "@components/text";
import { MagnifyingGlass } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";
import { useAvailableSuggestedReviewers } from "../hooks/useInboxReports";
import type { AvailableSuggestedReviewer, SuggestedReviewer } from "../types";
import { buildReviewerOptions, reviewerMatchesAvailable } from "../utils";
import { ReviewerOptionRow } from "./ReviewerOptionRow";

interface EditReviewersSheetProps {
  visible: boolean;
  reviewers: SuggestedReviewer[];
  meUuid?: string | null;
  onClose: () => void;
  onToggle: (option: AvailableSuggestedReviewer) => void;
}

export function EditReviewersSheet({
  visible,
  reviewers,
  meUuid,
  onClose,
  onToggle,
}: EditReviewersSheetProps) {
  const { bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const { data: available, isLoading } = useAvailableSuggestedReviewers({
    enabled: visible,
    query: debouncedQuery,
  });

  const options = useMemo(
    () => buildReviewerOptions(available?.results ?? [], meUuid ?? undefined),
    [available?.results, meUuid],
  );

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View
        className="flex-1 bg-background"
        style={{ paddingTop: sheetContentTop() }}
      >
        <View className="flex-row items-center justify-between border-gray-6 border-b px-4 pb-3">
          <Text className="font-semibold text-[18px] text-gray-12">
            Add reviewer
          </Text>
          <Pressable onPress={onClose}>
            <Text className="font-semibold text-[14px] text-accent-9">
              Done
            </Text>
          </Pressable>
        </View>

        <View className="px-4 pt-3">
          <View className="flex-row items-center gap-2 rounded-lg bg-gray-2 px-3 py-2">
            <MagnifyingGlass size={16} color={themeColors.gray[9]} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Filter users…"
              placeholderTextColor={themeColors.gray[9]}
              autoCapitalize="none"
              autoCorrect={false}
              className="min-w-0 flex-1 text-[14px] text-gray-12"
            />
          </View>
        </View>

        {options.length === 0 ? (
          isLoading ? (
            <View className="flex-1 items-center justify-center">
              <ActivityIndicator size="large" color={themeColors.accent[9]} />
            </View>
          ) : (
            <View className="flex-1 items-center justify-center p-6">
              <Text className="text-[14px] text-gray-10">No users found</Text>
            </View>
          )
        ) : (
          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingTop: 12,
              paddingBottom: bottom("roomy"),
            }}
          >
            {options.map((reviewer) => (
              <ReviewerOptionRow
                key={reviewer.uuid}
                reviewer={reviewer}
                selected={reviewers.some((r) =>
                  reviewerMatchesAvailable(r, reviewer),
                )}
                onPress={() => onToggle(reviewer)}
              />
            ))}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}
