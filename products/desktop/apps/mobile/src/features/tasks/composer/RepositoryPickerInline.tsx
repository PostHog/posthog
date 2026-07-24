import { Text } from "@components/text";
import { ArrowsClockwise, Check, MagnifyingGlass } from "phosphor-react-native";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import type { RepositoryOption } from "@/features/tasks/types";
import { useThemeColors } from "@/lib/theme";

// Tuning for the nested (ScrollView) path's progressive mount. The first
// chunk needs to cover the rows the user can actually see (~5 with the
// 240px height cap) plus a small buffer so a quick flick scroll doesn't
// hit empty space. Subsequent chunks fill in over the next few frames.
const NESTED_INITIAL_RENDER = 30;
const NESTED_RENDER_CHUNK = 100;
const NESTED_RENDER_INTERVAL_MS = 16;

interface RepositoryPickerInlineProps {
  open: boolean;
  repositoryOptions: RepositoryOption[];
  selected: RepositoryOption | null;
  /** True when we have no data to show yet (no cache, fresh fetch in flight).
   *  Mutually exclusive with `isRefreshing` from the caller's perspective. */
  loading?: boolean;
  /** True when we're rendering cached data while a background refetch runs.
   *  Surfaces as a small spinner badge instead of a blocking state. */
  isRefreshing?: boolean;
  /** Set when this picker lives inside a parent `ScrollView`/`FlatList` of
   *  the same orientation (e.g. the automation form). Disables the
   *  internal `FlatList` and uses a plain `ScrollView` instead, since
   *  React Native warns about nested VirtualizedLists. Default `false`
   *  keeps `FlatList`'s windowing so opening with many repos is instant. */
  nested?: boolean;
  onChange: (option: RepositoryOption) => void;
  onClose: () => void;
}

/**
 * Inline repository picker that pops up above the composer with a quick
 * fade + lift animation. Lives in the screen tree (no Modal) so it stays
 * with the layout when the keyboard moves, and feels more like a dropdown
 * than a bottom sheet. Tap a row to select; tap outside the card (handled
 * by the caller's backdrop) or onClose to dismiss.
 */
export function RepositoryPickerInline({
  open,
  repositoryOptions,
  selected,
  loading,
  isRefreshing,
  nested = false,
  onChange,
  onClose,
}: RepositoryPickerInlineProps) {
  const themeColors = useThemeColors();
  const [search, setSearch] = useState("");
  const searchInputRef = useRef<TextInput>(null);

  // Reset the search on each open so the user starts with the full list.
  useEffect(() => {
    if (open) {
      setSearch("");
      // Focusing the search lets the user type immediately. Slight delay
      // gives the popover its animation frame so the keyboard rise feels
      // synced with the popover entrance.
      const t = setTimeout(() => searchInputRef.current?.focus(), 80);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Entrance/exit animation — fade + small upward translate so it reads as
  // a dropdown popping out of the pill rather than a slide-in sheet.
  const progress = useSharedValue(0);
  useEffect(() => {
    progress.value = withTiming(open ? 1 : 0, {
      duration: open ? 160 : 120,
      easing: Easing.out(Easing.cubic),
    });
  }, [open, progress]);

  const cardStyle = useAnimatedStyle(() => ({
    opacity: progress.value,
    transform: [{ translateY: (1 - progress.value) * 8 }],
  }));

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return repositoryOptions;
    return repositoryOptions.filter(
      (option) =>
        option.repository.toLowerCase().includes(q) ||
        option.integrationLabel.toLowerCase().includes(q),
    );
  }, [repositoryOptions, search]);

  // Keep the popover mounted briefly after `open` flips to false so the
  // exit animation can play. Unmount after the animation duration.
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const t = setTimeout(() => setMounted(false), 140);
    return () => clearTimeout(t);
  }, [open]);

  // Progressive row mount for the nested (ScrollView) path. Without this,
  // opening the picker on a screen with hundreds of repos would block the
  // entrance animation while every row materializes synchronously. We
  // mount a small first batch (enough to fill the visible area), then
  // grow the slice every frame until the list is complete. The FlatList
  // path doesn't need this because `initialNumToRender` already windows
  // its initial mount.
  const [nestedRenderedCount, setNestedRenderedCount] = useState(
    NESTED_INITIAL_RENDER,
  );
  // Reset whenever the picker reopens or the filtered set changes (e.g.
  // the user typed a query, or new data arrived from a background
  // refetch). Reusing a stale `renderedCount` across filter changes would
  // either show too few rows (after broadening the filter) or be wasted.
  useEffect(() => {
    if (!nested) return;
    if (!open) return;
    setNestedRenderedCount(NESTED_INITIAL_RENDER);
  }, [nested, open]);
  useEffect(() => {
    if (!nested) return;
    if (!open) return;
    if (nestedRenderedCount >= filtered.length) return;
    const t = setTimeout(() => {
      setNestedRenderedCount((current) =>
        Math.min(current + NESTED_RENDER_CHUNK, filtered.length),
      );
    }, NESTED_RENDER_INTERVAL_MS);
    return () => clearTimeout(t);
  }, [nested, open, nestedRenderedCount, filtered.length]);

  // Hoisted row renderer so both the ScrollView and FlatList paths share
  // identical row markup without duplicating the closure.
  const renderRow = (item: RepositoryOption) => {
    const isSelected =
      item.integrationId === selected?.integrationId &&
      item.repository === selected.repository;
    return (
      <Pressable
        key={`${item.integrationId}:${item.repository}`}
        onPress={() => {
          onChange(item);
          onClose();
        }}
        className={`flex-row items-center gap-2 px-3 py-2.5 active:bg-gray-2 ${
          isSelected ? "bg-accent-3" : ""
        }`}
      >
        <View className="min-w-0 flex-1">
          <Text
            className={`text-[13px] ${
              isSelected ? "text-accent-11" : "text-gray-12"
            }`}
            numberOfLines={1}
          >
            {item.repository}
          </Text>
          <Text className="mt-0.5 text-[11px] text-gray-10">
            {item.integrationLabel}
          </Text>
        </View>
        {isSelected ? (
          <Check size={14} color={themeColors.accent[9]} weight="bold" />
        ) : null}
      </Pressable>
    );
  };

  if (!mounted) return null;

  return (
    <Animated.View
      style={cardStyle}
      className="overflow-hidden rounded-2xl border border-gray-6 bg-card"
    >
      {/* Header: title + search + background-refresh indicator */}
      <View className="border-gray-6 border-b px-3 pt-3 pb-2">
        <View className="mb-2 flex-row items-center justify-between">
          <Text className="font-semibold text-[14px] text-gray-12">
            Repository
          </Text>
          <View className="flex-row items-center gap-2">
            {isRefreshing ? (
              <View className="flex-row items-center gap-1">
                <ArrowsClockwise size={11} color={themeColors.gray[9]} />
                <Text className="text-[11px] text-gray-9">Refreshing…</Text>
              </View>
            ) : null}
            <Pressable
              onPress={onClose}
              hitSlop={8}
              accessibilityLabel="Close repository picker"
              accessibilityRole="button"
              className="px-1 py-0.5 active:opacity-60"
            >
              <Text className="text-[12px] text-gray-10">Done</Text>
            </Pressable>
          </View>
        </View>
        <View className="flex-row items-center gap-2 rounded-md border border-gray-6 bg-gray-2 px-2.5 py-1.5">
          <MagnifyingGlass size={14} color={themeColors.gray[10]} />
          <TextInput
            ref={searchInputRef}
            className="flex-1 text-[13px] text-gray-12"
            placeholder="Search repositories"
            placeholderTextColor={themeColors.gray[9]}
            value={search}
            onChangeText={setSearch}
            autoCapitalize="none"
            autoCorrect={false}
            clearButtonMode="while-editing"
            returnKeyType="search"
          />
        </View>
      </View>

      {loading ? (
        <View className="items-center px-4 py-8">
          <ActivityIndicator size="small" color={themeColors.accent[9]} />
          <Text className="mt-2 text-[12px] text-gray-10">
            Loading repositories…
          </Text>
        </View>
      ) : filtered.length === 0 ? (
        <View className="items-center px-4 py-6">
          <Text className="text-center text-[13px] text-gray-10">
            {search
              ? `No repositories match “${search}”`
              : "No repositories available"}
          </Text>
        </View>
      ) : nested ? (
        // ScrollView path — used when the picker lives inside a parent
        // ScrollView (e.g. the automation form). Plain `.map()` because
        // RN warns about nested VirtualizedLists. Rows are mounted
        // progressively via `nestedRenderedCount` so opening with many
        // repos doesn't block the entrance animation.
        <ScrollView
          style={{ maxHeight: 240 }}
          contentContainerStyle={{ paddingVertical: 4 }}
          keyboardShouldPersistTaps="handled"
          nestedScrollEnabled
        >
          {filtered
            .slice(0, nestedRenderedCount)
            .map((item) => renderRow(item))}
        </ScrollView>
      ) : (
        // FlatList path — default. Windowing keeps the open animation
        // snappy even when the user has hundreds of repos, by only
        // mounting the visible rows up front.
        <FlatList
          data={filtered}
          keyExtractor={(item) => `${item.integrationId}:${item.repository}`}
          keyboardShouldPersistTaps="handled"
          style={{ maxHeight: 240 }}
          contentContainerStyle={{ paddingVertical: 4 }}
          // Tuned so the first mount only pays for the rows the user
          // actually sees, then fills in lazily as they scroll.
          initialNumToRender={12}
          maxToRenderPerBatch={20}
          windowSize={5}
          removeClippedSubviews
          renderItem={({ item }) => renderRow(item)}
        />
      )}
    </Animated.View>
  );
}
