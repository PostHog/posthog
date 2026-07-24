import { Text } from "@components/text";
import { useMemo } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { useUserQuery } from "@/features/auth";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";
import { useAvailableSuggestedReviewers } from "../hooks/useInboxReports";
import { useInboxFilterStore } from "../stores/inboxFilterStore";
import { buildReviewerOptions } from "../utils";
import { ReviewerOptionRow } from "./ReviewerOptionRow";

interface ReviewerFilterSheetProps {
  visible: boolean;
  onClose: () => void;
}

export function ReviewerFilterSheet({
  visible,
  onClose,
}: ReviewerFilterSheetProps) {
  const { bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const { data: currentUser } = useUserQuery();
  const { data: available, isLoading } = useAvailableSuggestedReviewers();

  const suggestedReviewerFilter = useInboxFilterStore(
    (s) => s.suggestedReviewerFilter,
  );
  const toggleSuggestedReviewer = useInboxFilterStore(
    (s) => s.toggleSuggestedReviewer,
  );
  const setSuggestedReviewerFilter = useInboxFilterStore(
    (s) => s.setSuggestedReviewerFilter,
  );

  const options = useMemo(
    () => buildReviewerOptions(available?.results ?? [], currentUser?.uuid),
    [available?.results, currentUser?.uuid],
  );

  const hasSelection = suggestedReviewerFilter.length > 0;

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
        {/* Header */}
        <View className="flex-row items-center justify-between border-gray-6 border-b px-4 pb-3">
          <Text className="font-semibold text-[18px] text-gray-12">
            Suggested Reviewer
          </Text>
          <View className="flex-row items-center gap-3">
            {hasSelection && (
              <Pressable onPress={() => setSuggestedReviewerFilter([])}>
                <Text className="text-[14px] text-accent-9">Clear</Text>
              </Pressable>
            )}
            <Pressable onPress={onClose}>
              <Text className="font-semibold text-[14px] text-accent-9">
                Done
              </Text>
            </Pressable>
          </View>
        </View>

        {isLoading && options.length === 0 ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator size="large" color={themeColors.accent[9]} />
          </View>
        ) : options.length === 0 ? (
          <View className="flex-1 items-center justify-center p-6">
            <Text className="text-[14px] text-gray-10">No reviewers found</Text>
          </View>
        ) : (
          <ScrollView
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingTop: 12,
              paddingBottom: bottom("roomy"),
            }}
          >
            {options.map((reviewer, index) => {
              const showDivider = reviewer.isMe && index < options.length - 1;
              return (
                <View key={reviewer.uuid}>
                  <ReviewerOptionRow
                    reviewer={reviewer}
                    selected={suggestedReviewerFilter.includes(reviewer.uuid)}
                    onPress={() => toggleSuggestedReviewer(reviewer.uuid)}
                  />
                  {showDivider && (
                    <View className="mx-2 my-1 border-gray-6 border-t" />
                  )}
                </View>
              );
            })}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}
