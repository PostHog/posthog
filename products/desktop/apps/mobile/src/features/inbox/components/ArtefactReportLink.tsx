import { Text } from "@components/text";
import { reportLinkKindLabel } from "@posthog/core/inbox/activityLog";
import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import type { ReportLinkContent } from "@posthog/shared/domain-types";
import { useRouter } from "expo-router";
import { CaretRight } from "phosphor-react-native";
import { Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useInboxReport } from "../hooks/useInboxReports";

export function ArtefactReportLink({
  content,
}: {
  content: ReportLinkContent;
}) {
  const router = useRouter();
  const themeColors = useThemeColors();
  const linkedQuery = useInboxReport(content.report_id);

  if (!content.report_id) return null;

  const linked = linkedQuery.data;
  const title = linked
    ? humanizeReportTitle(linked.title, "Untitled report")
    : "Open report";

  return (
    <View className="gap-1">
      <Pressable
        onPress={() => router.push(`/inbox/${content.report_id}`)}
        hitSlop={4}
        accessibilityRole="button"
        className="flex-row items-center gap-2 py-1 active:opacity-60"
      >
        <View className="rounded bg-gray-4 px-1.5 py-0.5">
          <Text className="font-medium text-[11px] text-gray-11">
            {reportLinkKindLabel(content.kind)}
          </Text>
        </View>
        <Text
          className="min-w-0 flex-1 text-[13px] text-gray-12"
          numberOfLines={1}
        >
          {linkedQuery.isLoading ? "Loading report…" : title}
        </Text>
        <CaretRight size={14} color={themeColors.gray[9]} />
      </Pressable>
      {content.reason?.trim() ? (
        <Text className="text-[12px] text-gray-10">{content.reason}</Text>
      ) : null}
    </View>
  );
}
