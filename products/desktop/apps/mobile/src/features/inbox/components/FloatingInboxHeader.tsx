import { Text } from "@components/text";
import { LinearGradient } from "expo-linear-gradient";
import { FunnelSimple, UsersThree } from "phosphor-react-native";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { MenuButton } from "@/features/navigation/components/MenuButton";
import { toRgba, useThemeColors } from "@/lib/theme";
import { LiveDot } from "./LiveDot";

interface FloatingInboxHeaderProps {
  isFetching: boolean;
  hasError: boolean;
  reviewerFilterCount: number;
  showFilters?: boolean;
  onReviewerPress: () => void;
  onFilterPress: () => void;
}

/**
 * Floating header for the inbox screen — hamburger menu on the left,
 * centered "Inbox" title with live-polling indicator, and reviewer / filter
 * buttons on the right. Sits over the content with a top-to-bottom fade so
 * the list disappears gracefully behind it.
 */
export function FloatingInboxHeader({
  isFetching,
  hasError,
  reviewerFilterCount,
  showFilters = true,
  onReviewerPress,
  onFilterPress,
}: FloatingInboxHeaderProps) {
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();

  const fadeHeight = insets.top + 80;

  return (
    <View
      pointerEvents="box-none"
      className="absolute inset-x-0 top-0 z-10"
      style={{ height: fadeHeight }}
    >
      <LinearGradient
        pointerEvents="none"
        colors={[
          toRgba(themeColors.background, 1),
          toRgba(themeColors.background, 0.92),
          toRgba(themeColors.background, 0),
        ]}
        locations={[0, 0.65, 1]}
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
      />

      <View
        className="flex-row items-center justify-between px-3"
        style={{ paddingTop: insets.top + 6, paddingBottom: 8 }}
      >
        <MenuButton />

        <View
          pointerEvents="none"
          className="absolute inset-x-0 flex-row items-center justify-center gap-1.5"
          style={{ top: insets.top + 6, bottom: 8 }}
        >
          <Text
            className="font-semibold text-[15px] text-gray-12"
            numberOfLines={1}
          >
            Inbox
          </Text>
          <LiveDot active={isFetching} hasError={hasError} />
        </View>

        <View className="flex-row items-center gap-2">
          {showFilters ? (
            <>
              <Pressable
                onPress={onReviewerPress}
                hitSlop={8}
                accessibilityLabel="Filter by reviewer"
                accessibilityRole="button"
                className={`h-9 flex-row items-center justify-center gap-1 rounded-md border border-gray-6 px-2 active:bg-gray-3 ${
                  reviewerFilterCount > 0 ? "bg-gray-3" : "bg-gray-2"
                }`}
              >
                <UsersThree
                  size={16}
                  color={
                    reviewerFilterCount > 0
                      ? themeColors.gray[12]
                      : themeColors.gray[11]
                  }
                />
                {reviewerFilterCount > 0 && (
                  <Text className="font-medium text-[12px] text-gray-12">
                    {reviewerFilterCount}
                  </Text>
                )}
              </Pressable>
              <Pressable
                onPress={onFilterPress}
                hitSlop={8}
                accessibilityLabel="Filter and sort reports"
                accessibilityRole="button"
                className="h-9 w-9 items-center justify-center rounded-md border border-gray-6 bg-gray-2 active:bg-gray-3"
              >
                <FunnelSimple size={16} color={themeColors.gray[11]} />
              </Pressable>
            </>
          ) : (
            // Keep horizontal space reserved so the title stays centered.
            <View className="h-9 w-9" />
          )}
        </View>
      </View>
    </View>
  );
}
