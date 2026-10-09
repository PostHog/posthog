import { Text } from "@components/text";
import { sourceSuggestionTarget } from "@posthog/core/inbox/sourceSuggestion";
import type {
  SignalReport,
  SignalReportSourceSuggestion,
} from "@posthog/shared/domain-types";
import {
  ArrowSquareOut,
  Bug,
  ChatCircle,
  type Icon,
  ListBullets,
  Robot,
} from "phosphor-react-native";
import { useEffect, useRef } from "react";
import { Pressable, View } from "react-native";
import { useAuthStore } from "@/features/auth";
import {
  ANALYTICS_EVENTS,
  computeReportAgeHours,
  useAnalytics,
} from "@/lib/analytics";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";

const PRODUCT_META: Record<string, { label: string; icon: Icon }> = {
  logs: { label: "Logs", icon: ListBullets },
  session_replay: { label: "Session replay", icon: ChatCircle },
  error_tracking: { label: "Error tracking", icon: Bug },
  llm_analytics: { label: "LLM observability", icon: Robot },
};

function eventProperties(report: SignalReport, product: string) {
  return {
    report_id: report.id,
    report_age_hours: computeReportAgeHours(report.created_at),
    priority: report.priority ?? null,
    actionability: report.actionability ?? null,
    has_pr: !!report.implementation_pr_url,
    product,
  };
}

export function ReportSourceSuggestion({
  report,
  suggestion,
}: {
  report: SignalReport;
  suggestion: SignalReportSourceSuggestion;
}) {
  const themeColors = useThemeColors();
  const analytics = useAnalytics();
  const { projectId, cloudRegion, getCloudUrlFromRegion } = useAuthStore();

  const target = sourceSuggestionTarget(suggestion.product);
  const meta = PRODUCT_META[suggestion.product] ?? null;
  const url =
    target && projectId !== null && cloudRegion !== null
      ? `${getCloudUrlFromRegion(cloudRegion)}/project/${projectId}/${target.path}`
      : null;
  const canRender = target !== null && url !== null && meta !== null;

  // Once per report and product; React strict mode would otherwise double-fire.
  const shownKey = canRender ? `${report.id}:${suggestion.product}` : null;
  const shownKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (shownKey === null || shownKeyRef.current === shownKey) return;
    shownKeyRef.current = shownKey;
    analytics.track(
      ANALYTICS_EVENTS.INBOX_REPORT_SOURCE_SUGGESTION_SHOWN,
      eventProperties(report, suggestion.product),
    );
  }, [shownKey, report, suggestion.product, analytics]);

  if (!target || !url || !meta) return null;

  const Icon = meta.icon;

  return (
    <View className="rounded-xl border border-gray-6 border-dashed bg-gray-1 p-3">
      <View className="mb-1.5 flex-row items-center gap-1.5">
        <Icon size={13} color={themeColors.gray[11]} />
        <Text className="font-medium text-[12px] text-gray-11">
          {meta.label}
        </Text>
        <Text className="text-[12px] text-gray-9">
          · Not set up in this project
        </Text>
      </View>
      <Text className="mb-2 text-[13px] text-gray-12">{suggestion.reason}</Text>
      <Pressable
        onPress={() => {
          analytics.track(
            ANALYTICS_EVENTS.INBOX_REPORT_SOURCE_SUGGESTION_CLICKED,
            eventProperties(report, suggestion.product),
          );
          openExternalUrl(url);
        }}
        accessibilityRole="button"
        accessibilityLabel={target.actionLabel}
        hitSlop={6}
        className="flex-row items-center gap-1.5 self-start rounded-full border border-gray-6 bg-background px-3 py-2 active:opacity-70"
      >
        <ArrowSquareOut size={12} color={themeColors.gray[11]} />
        <Text className="font-medium text-[12px] text-gray-11">
          {target.actionLabel}
        </Text>
      </Pressable>
    </View>
  );
}
