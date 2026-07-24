import { Text } from "@components/text";
import { Eye, Plus, X } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import type {
  InboxReportActionProperties,
  InboxReportActionType,
} from "@/lib/analytics";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import { useUpdateSuggestedReviewers } from "../hooks/useInboxReports";
import type {
  AvailableSuggestedReviewer,
  SuggestedReviewer,
  SuggestedReviewersArtefact,
} from "../types";
import {
  orderSuggestedReviewers,
  reviewerMatchesAvailable,
  toSuggestedReviewerWriteContent,
} from "../utils";
import { EditReviewersSheet } from "./EditReviewersSheet";

export type ReviewerActionExtra = Pick<
  InboxReportActionProperties,
  "suggested_reviewer_login" | "suggested_reviewer_uuid"
>;

interface SuggestedReviewersProps {
  reportId: string;
  artefact: SuggestedReviewersArtefact;
  meUuid?: string | null;
  fireAction: (
    action: InboxReportActionType,
    extra?: ReviewerActionExtra,
  ) => void;
}

export function SuggestedReviewers({
  reportId,
  artefact,
  meUuid,
  fireAction,
}: SuggestedReviewersProps) {
  const themeColors = useThemeColors();
  const [editOpen, setEditOpen] = useState(false);
  const { mutate: updateReviewers, isPending } =
    useUpdateSuggestedReviewers(reportId);

  const reviewers = artefact.content;

  const displayReviewers = useMemo(
    () => orderSuggestedReviewers(reviewers, meUuid),
    [reviewers, meUuid],
  );

  const removeReviewer = (target: SuggestedReviewer) => {
    const next = reviewers.filter((r) => r !== target);
    fireAction("remove_suggested_reviewer", {
      suggested_reviewer_login: target.github_login || undefined,
      suggested_reviewer_uuid: target.user?.uuid,
    });
    updateReviewers({
      artefactId: artefact.id,
      content: toSuggestedReviewerWriteContent(next),
      optimisticReviewers: next,
    });
  };

  const toggleReviewer = (option: AvailableSuggestedReviewer) => {
    if (isPending) return;
    const existing = reviewers.find((r) => reviewerMatchesAvailable(r, option));
    if (existing) {
      removeReviewer(existing);
      return;
    }

    const optimisticEntry: SuggestedReviewer = {
      github_login: option.github_login,
      github_name: option.name || null,
      relevant_commits: [],
      user: {
        id: 0,
        uuid: option.uuid,
        email: option.email,
        first_name: option.name,
        last_name: "",
      },
    };
    fireAction("add_suggested_reviewer", {
      suggested_reviewer_login: option.github_login || undefined,
      suggested_reviewer_uuid: option.uuid,
    });
    updateReviewers({
      artefactId: artefact.id,
      content: [
        ...toSuggestedReviewerWriteContent(reviewers),
        { user_uuid: option.uuid },
      ],
      optimisticReviewers: [...reviewers, optimisticEntry],
    });
  };

  return (
    <View className="mb-4">
      <View className="mb-2 flex-row items-center gap-2">
        <Text className="font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
          Suggested reviewers
        </Text>
        {isPending && (
          <ActivityIndicator size="small" color={themeColors.gray[9]} />
        )}
        <View className="flex-1" />
        <Pressable
          onPress={() => setEditOpen(true)}
          disabled={isPending}
          accessibilityLabel="Add suggested reviewer"
          hitSlop={6}
          className="flex-row items-center gap-1 rounded-full border border-gray-6 px-2.5 py-1 active:opacity-70 disabled:opacity-50"
        >
          <Plus size={12} color={themeColors.gray[11]} weight="bold" />
          <Text className="text-[12px] text-gray-11">Add</Text>
        </Pressable>
      </View>

      {displayReviewers.length === 0 ? (
        <Text className="text-[13px] text-gray-9">
          No reviewers assigned. Use “Add” to suggest one.
        </Text>
      ) : (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 8 }}
        >
          {displayReviewers.map((reviewer) => {
            const isMe =
              !!reviewer.user?.uuid &&
              !!meUuid &&
              reviewer.user.uuid === meUuid;
            const displayName =
              reviewer.user?.first_name ??
              reviewer.github_name ??
              reviewer.github_login;
            return (
              <View
                key={reviewer.user?.uuid ?? reviewer.github_login}
                className="flex-row items-center gap-2 rounded-full border border-gray-6 bg-gray-2 py-1.5 pr-1.5 pl-1.5"
              >
                <Pressable
                  onPress={() => {
                    fireAction("click_suggested_reviewer", {
                      suggested_reviewer_login: reviewer.github_login,
                    });
                    openExternalUrl(
                      `https://github.com/${reviewer.github_login}`,
                    );
                  }}
                  hitSlop={4}
                  className="flex-row items-center gap-2 active:opacity-70"
                >
                  <Image
                    source={{
                      uri: `https://github.com/${reviewer.github_login}.png?size=48`,
                    }}
                    className="h-6 w-6 rounded-full bg-gray-4"
                  />
                  <Text className="text-[13px] text-gray-12">
                    {displayName}
                  </Text>
                  {isMe && (
                    <View className="rounded bg-status-warning/20 px-1 py-0.5">
                      <Eye
                        size={10}
                        color={themeColors.status.warning}
                        weight="bold"
                      />
                    </View>
                  )}
                </Pressable>
                <Pressable
                  onPress={() => removeReviewer(reviewer)}
                  disabled={isPending}
                  accessibilityLabel={`Remove ${displayName}`}
                  hitSlop={6}
                  className="h-5 w-5 items-center justify-center rounded-full active:bg-gray-4 disabled:opacity-50"
                >
                  <X size={12} color={themeColors.gray[10]} weight="bold" />
                </Pressable>
              </View>
            );
          })}
        </ScrollView>
      )}

      <EditReviewersSheet
        visible={editOpen}
        reviewers={reviewers}
        meUuid={meUuid}
        onClose={() => setEditOpen(false)}
        onToggle={toggleReviewer}
      />
    </View>
  );
}
