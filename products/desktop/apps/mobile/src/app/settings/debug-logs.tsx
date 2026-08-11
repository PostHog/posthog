import { Text } from "@components/text";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { Stack } from "expo-router";
import { Copy, Trash } from "phosphor-react-native";
import { useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  clearLogEntries,
  formatLogEntries,
  getLogEntries,
  type LogEntry,
  type LogLevel,
  subscribeToLogEntries,
} from "@/lib/logBuffer";
import { useThemeColors } from "@/lib/theme";

const LEVEL_FILTERS: Array<LogLevel | "all"> = [
  "all",
  "debug",
  "info",
  "warn",
  "error",
];

function levelClass(level: LogLevel): string {
  switch (level) {
    case "error":
      return "text-status-error";
    case "warn":
      return "text-status-warning";
    case "info":
      return "text-gray-12";
    default:
      return "text-gray-11";
  }
}

function timeLabel(ts: number): string {
  const d = new Date(ts);
  return `${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

/** Staff-only viewer over the in-memory log ring buffer (Settings → Debug
 *  info → Debug logs). Live-updating; newest entries first. */
export default function DebugLogsScreen() {
  const themeColors = useThemeColors();
  const insets = useSafeAreaInsets();
  const [entries, setEntries] = useState<LogEntry[]>(() => getLogEntries());
  const [levelFilter, setLevelFilter] = useState<LogLevel | "all">("all");
  const [copied, setCopied] = useState(false);

  useEffect(() => subscribeToLogEntries(() => setEntries(getLogEntries())), []);

  const visible = useMemo(() => {
    const filtered =
      levelFilter === "all"
        ? entries
        : entries.filter((e) => e.level === levelFilter);
    return [...filtered].reverse();
  }, [entries, levelFilter]);

  const handleCopy = async () => {
    await Clipboard.setStringAsync(formatLogEntries(entries));
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      <Stack.Screen options={{ headerShown: false }} />

      <View className="flex-row items-center justify-between px-4 pt-2 pb-3">
        <Text className="font-semibold text-[20px] text-gray-12">
          Debug logs
        </Text>
        <View className="flex-row items-center gap-2">
          <Pressable
            onPress={handleCopy}
            hitSlop={8}
            className="flex-row items-center gap-1.5 rounded-md border border-gray-6 bg-gray-3 px-3 py-1.5 active:opacity-60"
          >
            <Copy size={14} color={themeColors.gray[12]} />
            <Text className="font-medium text-[13px] text-gray-12">
              {copied ? "Copied!" : "Copy"}
            </Text>
          </Pressable>
          <Pressable
            onPress={clearLogEntries}
            hitSlop={8}
            className="flex-row items-center gap-1.5 rounded-md border border-gray-6 bg-gray-3 px-3 py-1.5 active:opacity-60"
          >
            <Trash size={14} color={themeColors.gray[12]} />
            <Text className="font-medium text-[13px] text-gray-12">Clear</Text>
          </Pressable>
        </View>
      </View>

      <View className="flex-row gap-1.5 px-4 pb-3">
        {LEVEL_FILTERS.map((level) => (
          <Pressable
            key={level}
            onPress={() => setLevelFilter(level)}
            className={`rounded-full border px-3 py-1 ${
              levelFilter === level
                ? "border-gray-12 bg-gray-12"
                : "border-gray-6 bg-gray-2"
            }`}
          >
            <Text
              className={`text-[12px] ${
                levelFilter === level
                  ? "font-medium text-background"
                  : "text-gray-11"
              }`}
            >
              {level}
            </Text>
          </Pressable>
        ))}
      </View>

      <FlatList
        data={visible}
        keyExtractor={(item, index) => `${item.ts}-${index}`}
        contentContainerStyle={{
          paddingHorizontal: 16,
          paddingBottom: insets.bottom + 16,
        }}
        ListEmptyComponent={
          <View className="items-center py-12">
            <Text className="text-[14px] text-gray-10">No log entries yet</Text>
          </View>
        }
        renderItem={({ item }) => (
          <View className="border-gray-4 border-b py-1.5">
            <View className="flex-row items-baseline gap-2">
              <Text className="font-mono text-[11px] text-gray-9">
                {timeLabel(item.ts)}
              </Text>
              <Text
                className={`font-mono text-[11px] uppercase ${levelClass(item.level)}`}
              >
                {item.level}
              </Text>
              <Text
                className="font-mono text-[11px] text-gray-10"
                numberOfLines={1}
              >
                [{item.scope}]
              </Text>
            </View>
            <Text className="font-mono text-[12px] text-gray-12" selectable>
              {item.message}
              {item.details ? ` ${item.details}` : ""}
            </Text>
          </View>
        )}
      />
    </View>
  );
}
