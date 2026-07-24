import { Text } from "@components/text";
import { Tray } from "phosphor-react-native";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useInboxReports } from "../hooks/useInboxReports";
import type { SignalReport } from "../types";
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

  const handlePress = (report: SignalReport) => {
    onReportPress?.(report);
  };

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

  if (reports.length === 0) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <View className="mb-6 h-16 w-16 items-center justify-center rounded-full bg-gray-3">
          <Tray size={28} color={themeColors.gray[10]} />
        </View>
        <Text className="mb-2 text-center font-semibold text-[16px] text-gray-12">
          Inbox is empty
        </Text>
        <Text className="text-center text-[13px] text-gray-11">
          Reports will appear here as signals come in.
        </Text>
      </View>
    );
  }

  return (
    <FlatList
      data={reports}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => (
        <ReportListRow report={item} onPress={handlePress} />
      )}
      refreshControl={
        <RefreshControl
          refreshing={isLoading}
          onRefresh={() => refetch()}
          tintColor={themeColors.accent[9]}
          progressViewOffset={contentInsetTop}
        />
      }
      onEndReachedThreshold={0.5}
      onEndReached={() => {
        if (hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      }}
      ListFooterComponent={
        isFetchingNextPage ? (
          <View className="py-4">
            <ActivityIndicator color={themeColors.accent[9]} />
          </View>
        ) : null
      }
      contentContainerStyle={{
        paddingTop: contentInsetTop,
        paddingBottom: 100,
      }}
    />
  );
}
