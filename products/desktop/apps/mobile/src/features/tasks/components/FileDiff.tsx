import { Text } from "@components/text";
import { Platform, View } from "react-native";
import { toRgba, useThemeColors } from "@/lib/theme";
import type { ChangedFile } from "../hooks/usePrChangedFiles";
import { type DiffLine, parsePatch } from "../utils/parsePatch";

interface FileDiffProps {
  file: ChangedFile;
}

const MONO_FONT = Platform.OS === "ios" ? "Menlo" : "monospace";

function statusLabel(status: ChangedFile["status"]): string {
  switch (status) {
    case "added":
      return "Added";
    case "removed":
      return "Deleted";
    case "renamed":
      return "Renamed";
    case "modified":
      return "Modified";
    default:
      return status;
  }
}

function linePrefix(type: DiffLine["type"]): string {
  if (type === "add") return "+";
  if (type === "delete") return "-";
  return " ";
}

export function FileDiff({ file }: FileDiffProps) {
  const themeColors = useThemeColors();
  const hunks = file.patch ? parsePatch(file.patch) : [];

  const addBg = toRgba(themeColors.status.success, 0.14);
  const delBg = toRgba(themeColors.status.error, 0.14);
  const hunkBg = themeColors.gray[3];

  const colorFor = (type: DiffLine["type"]): string => {
    if (type === "add") return themeColors.status.success;
    if (type === "delete") return themeColors.status.error;
    if (type === "no-newline") return themeColors.gray[9];
    return themeColors.gray[12];
  };
  const bgFor = (type: DiffLine["type"]): string => {
    if (type === "add") return addBg;
    if (type === "delete") return delBg;
    return "transparent";
  };

  return (
    <View className="mb-2 overflow-hidden rounded-lg border border-gray-6 bg-card">
      <View className="flex-row items-center gap-2 border-gray-6 border-b bg-gray-2 px-3 py-2">
        <Text
          numberOfLines={1}
          className="flex-1 font-medium text-[13px] text-gray-12"
        >
          {file.previous_filename
            ? `${file.previous_filename} → ${file.filename}`
            : file.filename}
        </Text>
        <Text
          className="text-[11px]"
          style={{
            color: themeColors.status.success,
            fontFamily: MONO_FONT,
          }}
        >
          +{file.additions}
        </Text>
        <Text
          className="text-[11px]"
          style={{ color: themeColors.status.error, fontFamily: MONO_FONT }}
        >
          −{file.deletions}
        </Text>
      </View>

      {hunks.length > 0 ? (
        hunks.map((hunk) => (
          <View key={hunk.header}>
            <View style={{ backgroundColor: hunkBg }} className="px-3 py-1">
              <Text
                style={{ fontFamily: MONO_FONT, color: themeColors.gray[10] }}
                className="text-[11px]"
              >
                {hunk.header}
              </Text>
            </View>
            {hunk.lines.map((line) => (
              <View
                key={line.key}
                style={{ backgroundColor: bgFor(line.type) }}
                className="px-3"
              >
                <Text
                  style={{ fontFamily: MONO_FONT, color: colorFor(line.type) }}
                  className="text-[11px] leading-[16px]"
                >
                  {linePrefix(line.type)}
                  {line.content}
                </Text>
              </View>
            ))}
          </View>
        ))
      ) : (
        <View className="px-3 py-3">
          <Text className="text-[12px] text-gray-10">
            {statusLabel(file.status)} — no preview available
          </Text>
        </View>
      )}
    </View>
  );
}
