import { Text } from "@components/text";
import { FileText, WarningCircle, X } from "phosphor-react-native";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { PendingAttachment } from "./types";

export type AttachmentStatus = "preparing" | "error";

interface AttachmentsBarProps {
  attachments: PendingAttachment[];
  onRemove: (id: string) => void;
  statuses?: Record<string, AttachmentStatus>;
}

function truncate(name: string, max = 18): string {
  if (name.length <= max) return name;
  const ext = name.lastIndexOf(".");
  if (ext > 0 && name.length - ext <= 6) {
    return `${name.slice(0, max - (name.length - ext) - 1)}…${name.slice(ext)}`;
  }
  return `${name.slice(0, max - 1)}…`;
}

function StatusOverlay({ status }: { status?: AttachmentStatus }) {
  const themeColors = useThemeColors();
  if (!status) return null;
  return (
    <View
      className="absolute inset-0 items-center justify-center rounded-lg bg-gray-1/70"
      accessibilityLabel={
        status === "preparing"
          ? "Preparing attachment"
          : "Attachment failed to prepare"
      }
    >
      {status === "preparing" ? (
        <ActivityIndicator size="small" color={themeColors.gray[12]} />
      ) : (
        <WarningCircle
          size={20}
          color={themeColors.status.error}
          weight="fill"
        />
      )}
    </View>
  );
}

export function AttachmentsBar({
  attachments,
  onRemove,
  statuses,
}: AttachmentsBarProps) {
  const themeColors = useThemeColors();
  if (attachments.length === 0) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      className="border-gray-5 border-b"
      contentContainerStyle={{
        paddingHorizontal: 8,
        paddingVertical: 8,
        gap: 8,
      }}
    >
      {attachments.map((att) => (
        <View
          key={att.id}
          className="relative h-16 rounded-lg border border-gray-6 bg-gray-2"
          style={{ minWidth: 64 }}
        >
          {att.kind === "image" ? (
            <Image
              source={{ uri: att.uri }}
              className="h-16 w-16 rounded-lg"
              resizeMode="cover"
            />
          ) : (
            <View className="h-16 w-32 flex-row items-center gap-2 px-2">
              <FileText
                size={20}
                color={themeColors.gray[11]}
                weight="regular"
              />
              <Text
                className="flex-1 text-[12px] text-gray-12"
                numberOfLines={2}
              >
                {truncate(att.fileName, 22)}
              </Text>
            </View>
          )}
          <StatusOverlay status={statuses?.[att.id]} />
          <Pressable
            onPress={() => onRemove(att.id)}
            hitSlop={8}
            accessibilityLabel={`Remove ${att.fileName}`}
            className="-top-1.5 -right-1.5 absolute h-5 w-5 items-center justify-center rounded-full bg-gray-12 active:opacity-80"
          >
            <X size={12} color={themeColors.background} weight="bold" />
          </Pressable>
        </View>
      ))}
    </ScrollView>
  );
}
