import { Text } from "@components/text";
import {
  deriveReportVerdict,
  type ReportVerdictTone,
} from "@posthog/core/inbox/reportVerdict";
import type { SignalReport } from "@posthog/shared/domain-types";
import { ArrowSquareOut, Play, Plus } from "phosphor-react-native";
import { ActivityIndicator, Pressable, View } from "react-native";
import { resolveReportVerdictAction } from "@/features/inbox/reportVerdictAction";
import { useThemeColors } from "@/lib/theme";

const TONE_CONTAINER: Record<ReportVerdictTone, string> = {
  decision: "border-status-warning/40 bg-status-warning/10",
  danger: "border-status-error/40 bg-status-error/10",
  progress: "border-gray-6 bg-gray-2",
  info: "border-gray-6 bg-gray-2",
};

interface ReportVerdictBannerProps {
  report: SignalReport;
  onStart: () => void;
  onOpenPr: (url: string) => void;
}

/**
 * Leads the report detail with its verdict: what state the report is in, what it
 * asks of the reader, and the one action that answers the ask.
 */
export function ReportVerdictBanner({
  report,
  onStart,
  onOpenPr,
}: ReportVerdictBannerProps) {
  const themeColors = useThemeColors();
  const action = resolveReportVerdictAction(report);
  const verdict = deriveReportVerdict(report, {
    hasExistingPr: action?.kind === "view_pr",
  });

  return (
    <View
      className={`mb-4 gap-2 rounded-xl border p-4 ${TONE_CONTAINER[verdict.tone]}`}
    >
      <View className="flex-row items-center gap-2">
        {verdict.tone === "progress" && (
          <ActivityIndicator size="small" color={themeColors.gray[11]} />
        )}
        <Text className="flex-1 font-semibold text-[15px] text-gray-12">
          {verdict.title}
        </Text>
      </View>
      <Text className="text-[13px] text-gray-11 leading-snug">
        {verdict.body}
      </Text>

      {action?.kind === "start" && (
        <Pressable
          onPress={onStart}
          accessibilityRole="button"
          accessibilityLabel={action.label}
          className="mt-1 flex-row items-center gap-2 self-start rounded-full bg-accent-9 px-4 py-2.5 active:opacity-80"
        >
          {action.awaitingInput ? (
            <Plus size={16} color="#ffffff" weight="bold" />
          ) : (
            <Play size={16} color="#ffffff" weight="fill" />
          )}
          <Text className="font-semibold text-[14px] text-white">
            {action.label}
          </Text>
        </Pressable>
      )}

      {action?.kind === "view_pr" && (
        <Pressable
          onPress={() => onOpenPr(action.url)}
          accessibilityRole="button"
          accessibilityLabel="View PR"
          className="mt-1 flex-row items-center gap-2 self-start rounded-full border border-gray-6 bg-background px-4 py-2.5 active:opacity-80"
        >
          <ArrowSquareOut size={16} color={themeColors.gray[12]} />
          <Text className="font-semibold text-[14px] text-gray-12">
            View PR
          </Text>
        </Pressable>
      )}
    </View>
  );
}
