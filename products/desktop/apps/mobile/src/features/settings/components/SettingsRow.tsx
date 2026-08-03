import { Text } from "@components/text";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

interface BaseRowProps {
  label: string;
  description?: string;
  /** Right-aligned content (value, switch, chevron, etc.). */
  rightSlot?: ReactNode;
  /** Set `false` to hide the bottom divider — typically the last row in a section. */
  showDivider?: boolean;
}

interface DisplayRowProps extends BaseRowProps {
  onPress?: never;
  disabled?: never;
}

interface PressableRowProps extends BaseRowProps {
  onPress: () => void;
  disabled?: boolean;
}

type SettingsRowProps = DisplayRowProps | PressableRowProps;

/**
 * One row inside a `SettingsSection`. Label + optional description on the
 * left, action / value on the right. Used as a building block for switch
 * rows, picker rows, info rows, and action rows.
 */
export function SettingsRow(props: SettingsRowProps) {
  const { label, description, rightSlot, showDivider = true } = props;
  const onPress = "onPress" in props ? props.onPress : undefined;
  const disabled = "disabled" in props ? props.disabled : undefined;

  const Body = (
    <View
      className={`flex-row items-center gap-3 px-4 py-3 ${showDivider ? "border-gray-5 border-b" : ""}`}
    >
      <View className="min-w-0 flex-1">
        <Text className="font-medium text-[15px] text-gray-12">{label}</Text>
        {description ? (
          <Text className="mt-0.5 text-[12px] text-gray-10 leading-snug">
            {description}
          </Text>
        ) : null}
      </View>
      {rightSlot ? (
        <View className="shrink-0 flex-row items-center gap-2">
          {rightSlot}
        </View>
      ) : null}
    </View>
  );

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        disabled={disabled}
        className={`active:bg-gray-2 ${disabled ? "opacity-50" : ""}`}
      >
        {Body}
      </Pressable>
    );
  }

  return Body;
}
