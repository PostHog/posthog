import { Text } from "@components/text";
import { Check } from "phosphor-react-native";
import { Image, Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { type ReviewerOption, reviewerOptionLabel } from "../utils";

interface ReviewerOptionRowProps {
  reviewer: ReviewerOption;
  selected: boolean;
  onPress: () => void;
}

export function ReviewerOptionRow({
  reviewer,
  selected,
  onPress,
}: ReviewerOptionRowProps) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center justify-between rounded-md px-2 py-2.5 active:bg-gray-3"
    >
      <View className="min-w-0 flex-1 flex-row items-center gap-2.5">
        {reviewer.github_login ? (
          <Image
            source={{
              uri: `https://github.com/${reviewer.github_login}.png?size=32`,
            }}
            className="h-6 w-6 rounded-full bg-gray-4"
          />
        ) : (
          <View className="h-6 w-6 items-center justify-center rounded-full bg-gray-4">
            <Text className="text-[11px] text-gray-10">
              {(reviewer.name || reviewer.email || "?")[0].toUpperCase()}
            </Text>
          </View>
        )}
        <View className="min-w-0 flex-1">
          <Text className="text-[14px] text-gray-12" numberOfLines={1}>
            {reviewerOptionLabel(reviewer)}
          </Text>
          {reviewer.email && (
            <Text className="text-[12px] text-gray-9" numberOfLines={1}>
              {reviewer.email}
            </Text>
          )}
        </View>
      </View>
      {selected && <Check size={16} color={themeColors.gray[12]} />}
    </Pressable>
  );
}
