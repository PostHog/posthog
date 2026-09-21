import { Text } from "@components/text";
import { partitionInboxReports } from "@posthog/core/inbox/reportInboxSections";
import type { SignalReport } from "@posthog/shared/domain-types";
import { Tray } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useArchivedReports, useInboxReports } from "../hooks/useInboxReports";
import { InboxReportSection } from "./InboxReportSection";
import { ReportListRow } from "./ReportListRow";

interface ReportListProps {
  onReportPress?: (report: SignalReport) => void;
  contentInsetTop?: number;
}

export function ReportList({
  onReportPress,
  contentInsetTop = 0,
}: ReportListProps) {
  const {
    reports,
    isLoading,
    error,
    refetch,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInboxReports();
  const themeColors = useThemeColors();

  const { reviewAndMerge, needsPr } = useMemo(
    () => partitionInboxReports(reports),
    [reports],
  );

  // Resolved (terminal) reports are loaded only when the section is opened.
  const isEmpty = reviewAndMerge.length === 0 && needsPr.length === 0;
  const [resolvedOpen, setResolvedOpen] = useState(false);
  const resolved = useArchivedReports({
    enabled: !isEmpty && resolvedOpen,
  });

  const handlePress = (report: SignalReport) => {
    onReportPress?.(report);
  };

  const renderReport = (report: SignalReport) => (
    <ReportListRow key={report.id} report={report} onPress={handlePress} />
  );

  if (error) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <Text className="mb-4 text-center text-status-error">{error}</Text>
        <Pressable
          onPress={() => refetch()}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (isLoading && reports.length === 0) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
        <Text className="mt-4 text-gray-11">Loading reports...</Text>
      </View>
    );
  }

  return (
    <ScrollView
      onScrollEndDrag={({ nativeEvent }) => {
        const { layoutMeasurement, contentOffset, contentSize } = nativeEvent;
        const nearBottom =
          layoutMeasurement.height + contentOffset.y >=
          contentSize.height - 200;
        if (nearBottom && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      }}
      scrollEventThrottle={200}
      refreshControl={
        <RefreshControl
          refreshing={isLoading}
          onRefresh={() => refetch()}
          tintColor={themeColors.accent[9]}
          progressViewOffset={contentInsetTop}
        />
      }
      contentContainerStyle={{
        paddingTop: contentInsetTop,
        paddingBottom: 100,
        flexGrow: 1,
      }}
    >
      {isEmpty ? (
        <View className="flex-1 items-center justify-center px-6 py-16">
          <Tray size={28} color={themeColors.gray[10]} />
          <Text className="mt-3 text-center font-semibold text-[16px] text-gray-12">
            Nothing to review
          </Text>
          <Text className="mt-1 text-center text-[13px] text-gray-11">
            Reports show up here as your agents find things worth acting on.
          </Text>
        </View>
      ) : (
        <>
          <InboxReportSection
            title="Review and merge"
            reports={reviewAndMerge}
            count={reviewAndMerge.length}
            emptyNote="No pull requests open yet. Start one from a report below."
            renderReport={renderReport}
          />
          <InboxReportSection
            title="Needs a PR"
            reports={needsPr}
            count={needsPr.length}
            emptyNote="No reports are waiting for a pull request."
            renderReport={renderReport}
          />
          {isFetchingNextPage ? (
            <View className="py-4">
              <ActivityIndicator color={themeColors.accent[9]} />
            </View>
          ) : null}
          <InboxReportSection
            title="Resolved"
            reports={resolved.reports}
            count={resolved.totalCount}
            defaultOpen={false}
            emptyNote="Nothing resolved or archived yet."
            onOpenChange={setResolvedOpen}
            renderReport={renderReport}
          />
        </>
      )}
    </ScrollView>
  );
}
