import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import { CaretDown, CaretUp, File as FileIcon } from "phosphor-react-native";
import { type ReactNode, useCallback, useState } from "react";
import {
  Alert,
  type LayoutChangeEvent,
  Pressable,
  Text,
  View,
} from "react-native";
import { formatRelativeTime } from "@/lib/format";
import { toRgba, useThemeColors } from "@/lib/theme";
import { MarkdownText } from "./MarkdownText";

export interface HumanMessageAttachment {
  kind: "image" | "document";
  uri: string;
  fileName: string;
  mimeType?: string;
  // Bytes stored as a cloud run artifact rather than on this device. When set,
  // the preview must be resolved through a presigned URL — the raw `uri` points
  // at the sandbox filesystem and is not fetchable here.
  cloudArtifact?: { runId: string; artifactId: string };
}

interface HumanMessageProps {
  content: string;
  timestamp?: number;
  attachments?: HumanMessageAttachment[];
  // Lets a host (e.g. tasks) resolve cloud-backed image previews. Without one,
  // attachments render as plain file chips.
  renderAttachment?: (attachment: HumanMessageAttachment) => ReactNode;
}

export function MessageFileChip({ fileName }: { fileName: string }) {
  const themeColors = useThemeColors();
  return (
    <View className="flex-row items-center gap-2 self-start rounded-md border border-gray-6 bg-gray-3 px-2 py-1.5">
      <FileIcon size={14} color={themeColors.gray[11]} />
      <Text className="font-mono text-[12px] text-gray-12" numberOfLines={1}>
        {fileName}
      </Text>
    </View>
  );
}

const COLLAPSED_MAX_HEIGHT = 160;

export function HumanMessage({
  content,
  timestamp,
  attachments,
  renderAttachment,
}: HumanMessageProps) {
  const themeColors = useThemeColors();
  const [isExpanded, setIsExpanded] = useState(false);
  const [contentHeight, setContentHeight] = useState<number | null>(null);

  const isOverflowing =
    contentHeight !== null && contentHeight > COLLAPSED_MAX_HEIGHT;
  const collapse = isOverflowing && !isExpanded;
  const hasContent = content.trim().length > 0;
  const hasAttachments = (attachments?.length ?? 0) > 0;

  const handleLongPress = useCallback(() => {
    Clipboard.setStringAsync(content).then(() => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Alert.alert("Copied", "Message copied to clipboard.");
    });
  }, [content]);

  const handleLayout = useCallback((e: LayoutChangeEvent) => {
    setContentHeight(e.nativeEvent.layout.height);
  }, []);

  return (
    <View className="px-4 py-2">
      <Pressable onLongPress={handleLongPress} delayLongPress={400}>
        <View
          className="mt-3 border-l-2 bg-gray-2 py-2 pr-3 pl-3"
          style={{ borderColor: themeColors.accent[9] }}
        >
          {hasContent && (
            <View
              style={{
                maxHeight: collapse ? COLLAPSED_MAX_HEIGHT : undefined,
                overflow: "hidden",
              }}
            >
              <View onLayout={handleLayout}>
                <MarkdownText content={content} />
              </View>
              {collapse && (
                <LinearGradient
                  pointerEvents="none"
                  colors={[
                    toRgba(themeColors.gray[2], 0),
                    toRgba(themeColors.gray[2], 1),
                  ]}
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    bottom: 0,
                    height: 48,
                  }}
                />
              )}
            </View>
          )}
          {hasContent && isOverflowing && (
            <Pressable
              onPress={() => setIsExpanded((v) => !v)}
              hitSlop={6}
              className="mt-1 flex-row items-center gap-1 self-start"
            >
              {isExpanded ? (
                <CaretUp size={12} color={themeColors.accent[11]} />
              ) : (
                <CaretDown size={12} color={themeColors.accent[11]} />
              )}
              <Text className="text-[12px] text-accent-11">
                {isExpanded ? "Show less" : "Show more"}
              </Text>
            </Pressable>
          )}
          {hasAttachments && (
            <View className={hasContent ? "mt-2 gap-2" : "gap-2"}>
              {attachments?.map((att) => (
                <View key={`${att.uri}-${att.fileName}`}>
                  {renderAttachment ? (
                    renderAttachment(att)
                  ) : (
                    <MessageFileChip fileName={att.fileName} />
                  )}
                </View>
              ))}
            </View>
          )}
        </View>
      </Pressable>
      {timestamp && (
        <Text className="mt-1 px-1 font-mono text-[10px] text-gray-8">
          {formatRelativeTime(timestamp)}
        </Text>
      )}
    </View>
  );
}
