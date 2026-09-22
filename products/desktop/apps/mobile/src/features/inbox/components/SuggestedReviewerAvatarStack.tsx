import { Text } from "@components/text";
import { toSuggestedReviewerWriteContent } from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import type { SignalReport } from "@posthog/shared/domain-types";
import { ActivityIndicator, Image, Pressable, View } from "react-native";
import { useUserQuery } from "@/features/auth";
import {
  ANALYTICS_EVENTS,
  computeReportAgeHours,
  useAnalytics,
} from "@/lib/analytics";
import { useThemeColors } from "@/lib/theme";
import {
  useInboxReportArtefacts,
  useUpdateSuggestedReviewers,
} from "../hooks/useInboxReports";

const MAX_VISIBLE = 4;
const OVERLAP = { marginLeft: -6 };

interface SuggestedReviewerAvatarStackProps {
  report: SignalReport;
}

export function SuggestedReviewerAvatarStack({
  report,
}: SuggestedReviewerAvatarStackProps) {
  const themeColors = useThemeColors();
  const { data: me } = useUserQuery();
  const { data: artefacts } = useInboxReportArtefacts(report.id, {
    staleTime: 5 * 60 * 1000,
    refetchInterval: false,
  });
  const { mutate: updateReviewers, isPending } = useUpdateSuggestedReviewers(
    report.id,
  );
  const analytics = useAnalytics();

  const reviewerArtefact = selectSuggestedReviewersArtefact(
    artefacts?.results ?? [],
  );
  const reviewers = (reviewerArtefact?.content ?? []).filter(
    (reviewer) => reviewer.github_login,
  );
  if (reviewers.length === 0) {
    return null;
  }

  const currentReviewer = reviewers.find(
    (reviewer) => reviewer.user?.uuid === me?.uuid,
  );
  const visible = reviewers.slice(0, MAX_VISIBLE);
  const overflow = reviewers.length - visible.length;

  const stack = (
    <View className="flex-row items-center">
      {visible.map((reviewer, index) => (
        <Image
          key={reviewer.github_login}
          source={{
            uri: `https://github.com/${reviewer.github_login}.png?size=48`,
          }}
          className="h-6 w-6 rounded-full border-2 border-background bg-gray-4"
          style={index > 0 ? OVERLAP : undefined}
        />
      ))}
      {overflow > 0 ? (
        <View
          className="h-6 min-w-6 items-center justify-center rounded-full border-2 border-background bg-gray-3 px-1"
          style={OVERLAP}
        >
          <Text className="font-semibold text-[10px] text-gray-11">
            +{overflow}
          </Text>
        </View>
      ) : null}
    </View>
  );

  if (!currentReviewer || !reviewerArtefact) {
    return stack;
  }

  const removeSelf = () => {
    const next = reviewerArtefact.content.filter(
      (reviewer) => reviewer.user?.uuid !== me?.uuid,
    );
    analytics.track(ANALYTICS_EVENTS.INBOX_REPORT_ACTION, {
      report_id: report.id,
      report_title: report.title ?? null,
      report_age_hours: computeReportAgeHours(report.created_at),
      priority: report.priority ?? null,
      actionability: report.actionability ?? null,
      action_type: "remove_suggested_reviewer",
      surface: "list_row",
      is_bulk: false,
      bulk_size: 1,
      rank: 0,
      list_size: 0,
      suggested_reviewer_login: currentReviewer.github_login || undefined,
      suggested_reviewer_uuid: currentReviewer.user?.uuid,
    });
    updateReviewers({
      artefactId: reviewerArtefact.id,
      content: toSuggestedReviewerWriteContent(next),
      optimisticReviewers: next,
    });
  };

  return (
    <Pressable
      onPress={removeSelf}
      disabled={isPending}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel="Remove yourself from reviewers"
      className="flex-row items-center gap-1.5 py-1 active:opacity-70"
    >
      {stack}
      {isPending ? (
        <ActivityIndicator size="small" color={themeColors.gray[9]} />
      ) : null}
    </Pressable>
  );
}
