import { Text } from "@components/text";
import { Check, Star } from "phosphor-react-native";
import type { ReactNode } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { useThemeColors } from "@/lib/theme";

export interface SelectOption<T extends string> {
  value: T;
  label: string;
  description?: string;
  icon?: ReactNode;
  disabled?: boolean;
}

interface SelectSheetProps<T extends string> {
  open: boolean;
  title: string;
  options: SelectOption<T>[];
  value: T;
  onChange: (value: T) => void;
  onClose: () => void;
  /** When set, each row shows a star. The value matching `favoriteValue` is
   *  filled; tapping any star calls `onToggleFavorite` and does not select. */
  favoriteValue?: T | null;
  onToggleFavorite?: (value: T) => void;
}

export function SelectSheet<T extends string>({
  open,
  title,
  options,
  value,
  onChange,
  onClose,
  favoriteValue,
  onToggleFavorite,
}: SelectSheetProps<T>) {
  const themeColors = useThemeColors();
  const showFavorites = !!onToggleFavorite;

  return (
    <SheetContainer open={open} onClose={onClose}>
      <View className="px-4 pt-2 pb-2">
        <Text className="font-semibold text-[16px] text-gray-12">{title}</Text>
      </View>

      <ScrollView className="max-h-96">
        {options.map((option) => {
          const selected = option.value === value;
          const isFavorite = showFavorites && option.value === favoriteValue;
          return (
            <Pressable
              key={option.value}
              onPress={() => {
                if (option.disabled) return;
                onChange(option.value);
                onClose();
              }}
              disabled={option.disabled}
              className={`flex-row items-center gap-3 px-4 py-3 ${
                option.disabled ? "opacity-40" : "active:bg-gray-2"
              }`}
            >
              {option.icon ? (
                <View className="h-5 w-5 shrink-0 items-center justify-center">
                  {option.icon}
                </View>
              ) : null}
              <View className="min-w-0 flex-1">
                <Text className="font-medium text-[15px] text-gray-12">
                  {option.label}
                </Text>
                {option.description ? (
                  <Text className="mt-0.5 text-[12px] text-gray-10">
                    {option.description}
                  </Text>
                ) : null}
              </View>
              {selected ? (
                <Check size={16} color={themeColors.accent[9]} weight="bold" />
              ) : null}
              {showFavorites ? (
                <Pressable
                  hitSlop={10}
                  onPress={() => onToggleFavorite?.(option.value)}
                  accessibilityRole="button"
                  accessibilityLabel={
                    isFavorite
                      ? `Stop using ${option.label} by default`
                      : `Use ${option.label} by default`
                  }
                  accessibilityState={{ selected: isFavorite }}
                  className="active:opacity-60"
                >
                  <Star
                    size={16}
                    color={
                      isFavorite ? themeColors.gray[12] : themeColors.gray[10]
                    }
                    weight={isFavorite ? "fill" : "regular"}
                  />
                </Pressable>
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </SheetContainer>
  );
}
