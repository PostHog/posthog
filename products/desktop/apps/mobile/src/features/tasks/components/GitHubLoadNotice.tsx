import { Text } from "@components/text";
import { Pressable, View } from "react-native";

interface GitHubLoadNoticeProps {
  message: string;
  onRetry: () => void;
  tone?: "error" | "warning";
}

export function GitHubLoadNotice({
  message,
  onRetry,
  tone = "error",
}: GitHubLoadNoticeProps) {
  const containerClassName =
    tone === "warning"
      ? "mb-4 rounded-lg border border-status-warning/30 bg-status-warning/10 p-3"
      : "mb-4 rounded-lg border border-status-error bg-status-error/10 p-3";
  const messageClassName =
    tone === "warning" ? "text-status-warning" : "text-status-error";

  return (
    <View className={containerClassName}>
      <Text className={`text-sm ${messageClassName}`}>{message}</Text>
      <Pressable
        onPress={onRetry}
        className="mt-3 self-start rounded-lg bg-gray-3 px-3 py-2"
      >
        <Text className="text-gray-12 text-sm">Retry</Text>
      </Pressable>
    </View>
  );
}
