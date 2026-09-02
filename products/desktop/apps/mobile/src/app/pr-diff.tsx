import { Text } from "@components/text";
import { useLocalSearchParams } from "expo-router";
import { ActivityIndicator, FlatList, View } from "react-native";
import { FileDiff } from "@/features/tasks/components/FileDiff";
import {
  type ChangedFile,
  usePrChangedFiles,
} from "@/features/tasks/hooks/usePrChangedFiles";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

export default function PrDiffScreen() {
  const { prUrl } = useLocalSearchParams<{ prUrl?: string }>();
  const themeColors = useThemeColors();
  const { bottom } = useScreenInsets();

  const { data: files, isLoading } = usePrChangedFiles(prUrl ?? null);

  if (isLoading) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
      </View>
    );
  }

  if (!files || files.length === 0) {
    return (
      <View className="flex-1 items-center justify-center bg-background px-6">
        <Text className="text-center text-[14px] text-gray-11">
          No file diffs available.{"\n"}
          Private repositories require authentication.
        </Text>
      </View>
    );
  }

  const totalAdditions = files.reduce((s, f) => s + f.additions, 0);
  const totalDeletions = files.reduce((s, f) => s + f.deletions, 0);

  return (
    <FlatList<ChangedFile>
      data={files}
      keyExtractor={(f) => f.filename}
      renderItem={({ item }) => <FileDiff file={item} />}
      className="flex-1 bg-background"
      contentContainerStyle={{
        paddingHorizontal: 12,
        paddingTop: 8,
        paddingBottom: bottom("default"),
      }}
      ListHeaderComponent={
        <View className="mb-2 flex-row items-center justify-between px-1 py-1">
          <Text className="text-[13px] text-gray-11">
            {files.length} file{files.length === 1 ? "" : "s"} changed
          </Text>
          <View className="flex-row items-center gap-2">
            <Text
              className="text-[13px]"
              style={{ color: themeColors.status.success }}
            >
              +{totalAdditions}
            </Text>
            <Text
              className="text-[13px]"
              style={{ color: themeColors.status.error }}
            >
              −{totalDeletions}
            </Text>
          </View>
        </View>
      }
    />
  );
}
