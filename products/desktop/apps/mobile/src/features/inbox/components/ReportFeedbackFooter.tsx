import { Text } from "@components/text";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { ThumbsDown, ThumbsUp } from "phosphor-react-native";
import { useCallback, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import {
  ANALYTICS_EVENTS,
  computeReportAgeHours,
  type InboxReportFeedbackSentiment,
  useAnalytics,
} from "@/lib/analytics";
import { useThemeColors } from "@/lib/theme";

/** Bounded to keep the note within the analytics client's per-property limit. */
const FEEDBACK_NOTE_MAX_LENGTH = 4000;

/**
 * Thumbs rating at the end of the report body. The rating submits on the first
 * tap; only once it's recorded does an optional note appear, so the note can
 * never gate the rating. Feedback is analytics-only — it never changes the
 * report's state. Mirrors the desktop/cloud feedback footer so ranking
 * analysis is comparable across clients.
 */
export function ReportFeedbackFooter({ report }: { report: SignalReport }) {
  const analytics = useAnalytics();
  const themeColors = useThemeColors();

  const [sentiment, setSentiment] =
    useState<InboxReportFeedbackSentiment | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteSent, setNoteSent] = useState(false);

  // Re-tapping the chosen thumb is a no-op rather than a second identical
  // feedback event; switching thumbs records the new sentiment.
  const chooseSentiment = useCallback(
    (next: InboxReportFeedbackSentiment) => {
      if (sentiment === next) return;
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      setSentiment(next);
      analytics.track(ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK, {
        report_id: report.id,
        report_age_hours: computeReportAgeHours(report.created_at),
        priority: report.priority ?? null,
        actionability: report.actionability ?? null,
        sentiment: next,
        has_pr: !!report.implementation_pr_url,
        surface: "detail_footer",
      });
    },
    [sentiment, analytics, report],
  );

  const submitNote = useCallback(() => {
    const trimmed = noteDraft.trim();
    if (!trimmed || !sentiment) return;
    analytics.track(ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK_NOTE, {
      report_id: report.id,
      report_age_hours: computeReportAgeHours(report.created_at),
      priority: report.priority ?? null,
      actionability: report.actionability ?? null,
      sentiment,
      has_pr: !!report.implementation_pr_url,
      surface: "detail_footer",
      note: trimmed.slice(0, FEEDBACK_NOTE_MAX_LENGTH),
    });
    setNoteDraft("");
    setNoteOpen(false);
    setNoteSent(true);
  }, [noteDraft, sentiment, analytics, report]);

  const isPositive = sentiment === "positive";
  const isNegative = sentiment === "negative";

  return (
    <View className="mt-2 border-gray-4 border-t pt-4">
      <View className="flex-row flex-wrap items-center gap-2">
        <Text className="text-[13px] text-gray-11">
          {sentiment ? "Thanks for the feedback" : "Was this report useful?"}
        </Text>
        <View className="flex-row items-center gap-1.5">
          <Pressable
            onPress={() => chooseSentiment("positive")}
            accessibilityRole="button"
            accessibilityLabel="This report was useful"
            accessibilityState={{ selected: isPositive }}
            hitSlop={6}
            className={`rounded-full border px-3 py-2 active:opacity-70 ${
              isPositive
                ? "border-accent-9 bg-accent-9"
                : "border-gray-6 bg-background"
            }`}
          >
            <ThumbsUp
              size={16}
              weight={isPositive ? "fill" : "regular"}
              color={isPositive ? "#ffffff" : themeColors.gray[11]}
            />
          </Pressable>
          <Pressable
            onPress={() => chooseSentiment("negative")}
            accessibilityRole="button"
            accessibilityLabel="This report was not useful"
            accessibilityState={{ selected: isNegative }}
            hitSlop={6}
            className={`rounded-full border px-3 py-2 active:opacity-70 ${
              isNegative
                ? "border-accent-9 bg-accent-9"
                : "border-gray-6 bg-background"
            }`}
          >
            <ThumbsDown
              size={16}
              weight={isNegative ? "fill" : "regular"}
              color={isNegative ? "#ffffff" : themeColors.gray[11]}
            />
          </Pressable>
        </View>
        {sentiment && !noteOpen && !noteSent && (
          <Pressable
            onPress={() => setNoteOpen(true)}
            hitSlop={6}
            className="rounded-full px-2 py-1 active:opacity-60"
          >
            <Text className="text-[13px] text-accent-11">Add a note</Text>
          </Pressable>
        )}
        {noteSent && (
          <Text className="text-[13px] text-gray-9">Note added</Text>
        )}
      </View>
      {noteOpen && (
        <View className="mt-3">
          <TextInput
            value={noteDraft}
            onChangeText={setNoteDraft}
            placeholder="What was useful or off?"
            placeholderTextColor={themeColors.gray[9]}
            multiline
            maxLength={FEEDBACK_NOTE_MAX_LENGTH}
            autoFocus
            className="min-h-[80px] rounded-xl bg-gray-2 px-3 py-3 text-[14px] text-gray-12"
            style={{ textAlignVertical: "top" }}
          />
          <View className="mt-2 flex-row items-center justify-end">
            <Pressable
              onPress={submitNote}
              disabled={noteDraft.trim().length === 0}
              accessibilityRole="button"
              accessibilityLabel="Send note"
              className={`rounded-full px-4 py-2.5 active:opacity-80 ${
                noteDraft.trim().length === 0 ? "bg-gray-4" : "bg-accent-9"
              }`}
            >
              <Text className="font-semibold text-[14px] text-white">Send</Text>
            </Pressable>
          </View>
        </View>
      )}
    </View>
  );
}
