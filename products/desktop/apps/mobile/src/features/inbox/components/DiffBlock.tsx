import { Text } from "@components/text";
import { ScrollView, View } from "react-native";
import { parseDiffLines } from "../activityLog";

const LINE_CLASS: Record<string, string> = {
  add: "bg-status-success/15 text-status-success",
  del: "bg-status-error/15 text-status-error",
  hunk: "text-gray-9",
  context: "text-gray-12",
};

export function DiffBlock({ diff }: { diff: string }) {
  const lines = parseDiffLines(diff);

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator
      className="max-h-72 rounded-lg border border-gray-6 bg-gray-2"
    >
      <View className="p-2">
        {lines.map((line, i) => (
          <Text
            // biome-ignore lint/suspicious/noArrayIndexKey: stable parse output, never reorders
            key={i}
            className={`font-mono text-[11px] leading-[16px] ${LINE_CLASS[line.kind]}`}
          >
            {line.text || " "}
          </Text>
        ))}
      </View>
    </ScrollView>
  );
}
