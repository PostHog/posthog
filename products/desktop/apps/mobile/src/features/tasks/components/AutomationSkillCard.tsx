import { CaretDown, CaretUp } from "phosphor-react-native";
import { useState } from "react";
import {
  type NativeSyntheticEvent,
  Pressable,
  type TextLayoutEventData,
  View,
} from "react-native";
import { Text } from "@/components/text";
import { useThemeColors } from "@/lib/theme";
import type { SkillStoreListEntry } from "../skills/types";

interface AutomationSkillCardProps {
  skill: SkillStoreListEntry;
  onPress: (skillName: string) => void;
}

export function AutomationSkillCard({
  skill,
  onPress,
}: AutomationSkillCardProps) {
  const themeColors = useThemeColors();
  const [isExpanded, setIsExpanded] = useState(false);
  const [hasMeasuredOverflow, setHasMeasuredOverflow] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const description =
    skill.description ?? "Shared automation starter from your team.";

  function handleTextLayout(
    event: NativeSyntheticEvent<TextLayoutEventData>,
  ): void {
    if (hasMeasuredOverflow) {
      return;
    }

    setIsOverflowing(event.nativeEvent.lines.length > 2);
    setHasMeasuredOverflow(true);
  }

  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => onPress(skill.name)}
      className="rounded-xl border border-gray-6 bg-gray-1 px-4 py-4 active:opacity-80"
    >
      <Text className="font-semibold text-[16px] text-gray-12">
        {skill.name}
      </Text>
      <View className="relative">
        <Text
          className="mt-2 text-gray-11 text-sm"
          numberOfLines={isExpanded ? undefined : 2}
        >
          {description}
        </Text>
        {!hasMeasuredOverflow && (
          <View
            className="pointer-events-none absolute inset-x-0 opacity-0"
            accessible={false}
          >
            <Text
              className="mt-2 text-gray-11 text-sm"
              onTextLayout={handleTextLayout}
            >
              {description}
            </Text>
          </View>
        )}
      </View>
      {isOverflowing && (
        <Pressable
          accessibilityRole="button"
          onPress={(event) => {
            event.stopPropagation();
            setIsExpanded((value) => !value);
          }}
          hitSlop={6}
          className="mt-1 flex-row items-center gap-1 self-start py-1 active:opacity-60"
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
    </Pressable>
  );
}
