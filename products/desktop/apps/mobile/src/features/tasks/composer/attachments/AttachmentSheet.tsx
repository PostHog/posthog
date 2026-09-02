import { Text } from "@components/text";
import { Camera, FileText, Image as ImageIcon } from "phosphor-react-native";
import { Pressable, View } from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { useThemeColors } from "@/lib/theme";

interface AttachmentSheetProps {
  open: boolean;
  onClose: () => void;
  onPickPhoto: () => void;
  onPickCamera: () => void;
  onPickDocument: () => void;
}

interface RowProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  onPress: () => void;
}

function Row({ icon, label, description, onPress }: RowProps) {
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center gap-3 px-4 py-3 active:bg-gray-2"
    >
      <View className="h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-3">
        {icon}
      </View>
      <View className="min-w-0 flex-1">
        <Text className="font-medium text-[15px] text-gray-12">{label}</Text>
        <Text className="mt-0.5 text-[12px] text-gray-10">{description}</Text>
      </View>
    </Pressable>
  );
}

export function AttachmentSheet({
  open,
  onClose,
  onPickPhoto,
  onPickCamera,
  onPickDocument,
}: AttachmentSheetProps) {
  const themeColors = useThemeColors();

  return (
    <SheetContainer open={open} onClose={onClose}>
      <View className="px-4 pt-2 pb-2">
        <Text className="font-semibold text-[16px] text-gray-12">
          Add attachment
        </Text>
      </View>

      <Row
        icon={
          <ImageIcon size={18} color={themeColors.gray[12]} weight="bold" />
        }
        label="Photo library"
        description="Pick a photo to share with the agent"
        onPress={() => {
          onClose();
          onPickPhoto();
        }}
      />
      <Row
        icon={<Camera size={18} color={themeColors.gray[12]} weight="bold" />}
        label="Take photo"
        description="Capture a new photo from the camera"
        onPress={() => {
          onClose();
          onPickCamera();
        }}
      />
      <Row
        icon={<FileText size={18} color={themeColors.gray[12]} weight="bold" />}
        label="File"
        description="Attach a text or code file from your device"
        onPress={() => {
          onClose();
          onPickDocument();
        }}
      />
    </SheetContainer>
  );
}
