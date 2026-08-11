import { Text } from "@components/text";
import type { Task } from "@posthog/shared";
import * as Haptics from "expo-haptics";
import {
  Archive,
  CaretDown,
  GitBranch,
  Plus,
  PushPin,
  PushPinSlash,
  Sparkle,
  X,
} from "phosphor-react-native";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  FlatList,
  LayoutAnimation,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useAwaitingInputTaskIds } from "../hooks/useAwaitingInputTasks";
import { usePinnedTasks } from "../hooks/usePinnedTasks";
import { useTasks } from "../hooks/useTasks";
import { useUserIntegrations } from "../hooks/useUserIntegrations";
import { useArchivedTasksStore } from "../stores/archivedTasksStore";
import { useTaskStore } from "../stores/taskStore";
import { buildTaskListItems } from "../utils/taskListItems";
import { GitHubConnectionPrompt } from "./GitHubConnectionPrompt";
import { GitHubLoadNotice } from "./GitHubLoadNotice";
import { SwipeableTaskItem } from "./SwipeableTaskItem";

interface TaskListProps {
  onTaskPress?: (taskId: string) => void;
  onCreateTask?: () => void;
  /** Top inset so the list can scroll behind a floating header. */
  contentInsetTop?: number;
  /** Fired when long-press multi-select starts/ends, so the parent can hide
   *  chrome (e.g. the new-task FAB) that overlaps the selection bar. */
  onSelectionModeChange?: (active: boolean) => void;
  /** Rendered above the first row, scrolling with the list. */
  listHeader?: ReactNode;
}

interface CreateTaskEmptyStateProps {
  onCreateTask?: () => void;
}

function CreateTaskEmptyState({ onCreateTask }: CreateTaskEmptyStateProps) {
  const themeColors = useThemeColors();

  return (
    <View className="flex-1 items-center justify-center px-8">
      <View
        className="mb-6 h-20 w-20 items-center justify-center rounded-full"
        style={{ backgroundColor: `${themeColors.accent[9]}1A` }}
      >
        <Sparkle size={36} color={themeColors.accent[9]} weight="fill" />
      </View>
      <Text className="mb-2 text-center font-semibold text-[22px] text-gray-12 leading-tight">
        Start your first task
      </Text>
      <Text className="mb-8 max-w-[280px] text-center text-[15px] text-gray-11 leading-snug">
        Describe what you want built, fixed, or investigated.
      </Text>
      {onCreateTask && (
        <Pressable
          onPress={onCreateTask}
          className="flex-row items-center gap-2 rounded-full px-6 py-3.5 active:opacity-80"
          style={{ backgroundColor: themeColors.accent[9] }}
        >
          <Plus size={18} color={themeColors.accent.contrast} weight="bold" />
          <Text className="font-semibold text-[15px] text-accent-contrast">
            New task
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function CollapseChevron({
  collapsed,
  color,
}: {
  collapsed: boolean;
  color: string;
}) {
  const progress = useRef(new Animated.Value(collapsed ? 1 : 0)).current;

  useEffect(() => {
    Animated.timing(progress, {
      toValue: collapsed ? 1 : 0,
      duration: 150,
      easing: Easing.out(Easing.ease),
      useNativeDriver: true,
    }).start();
  }, [collapsed, progress]);

  const rotate = progress.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "-90deg"],
  });

  return (
    <Animated.View style={{ transform: [{ rotate }] }}>
      <CaretDown size={12} color={color} weight="bold" />
    </Animated.View>
  );
}

interface GroupHeaderProps {
  label: string;
  count: number;
  collapsed: boolean;
  onPress: () => void;
  icon?: ReactNode;
  uppercase?: boolean;
}

function GroupHeader({
  label,
  count,
  collapsed,
  onPress,
  icon,
  uppercase = false,
}: GroupHeaderProps) {
  const themeColors = useThemeColors();

  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center gap-2 bg-gray-2 px-3 py-2 active:bg-gray-3"
      accessibilityRole="button"
      accessibilityState={{ expanded: !collapsed }}
      accessibilityLabel={`${label}, ${count} tasks`}
      accessibilityHint={
        collapsed ? "Expands the group" : "Collapses the group"
      }
    >
      <CollapseChevron collapsed={collapsed} color={themeColors.gray[10]} />
      {icon}
      <Text
        className={`flex-1 font-medium text-[12px] text-gray-11 ${uppercase ? "uppercase" : ""}`}
        style={uppercase ? { letterSpacing: 0.5 } : null}
        numberOfLines={1}
      >
        {label}
      </Text>
      <Text className="text-[11px] text-gray-9">{count}</Text>
    </Pressable>
  );
}

export function TaskList({
  onTaskPress,
  onCreateTask,
  contentInsetTop = 0,
  onSelectionModeChange,
  listHeader,
}: TaskListProps) {
  const { tasks, isLoading, error, refetch } = useTasks();
  const {
    error: integrationsError,
    hasGithubIntegration,
    refetch: refetchIntegrations,
  } = useUserIntegrations();
  const themeColors = useThemeColors();
  const { archivedTasks, archive, archiveMany, unarchive } =
    useArchivedTasksStore();
  const { isPinned, togglePin } = usePinnedTasks();
  const awaitingInputTaskIds = useAwaitingInputTaskIds();
  const organizeMode = useTaskStore((s) => s.organizeMode);
  const sortMode = useTaskStore((s) => s.sortMode);
  const collapsedGroups = useTaskStore((s) => s.collapsedGroups);
  const toggleGroupCollapsed = useTaskStore((s) => s.toggleGroupCollapsed);
  const [scrollEnabled, setScrollEnabled] = useState(true);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const selectionMode = selectedIds.size > 0;

  useEffect(() => {
    onSelectionModeChange?.(selectionMode);
  }, [selectionMode, onSelectionModeChange]);

  const exitSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const toggleSelected = useCallback((taskId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) {
        next.delete(taskId);
      } else {
        next.add(taskId);
      }
      return next;
    });
  }, []);

  const handleTaskPress = (task: Task) => {
    if (selectionMode) {
      toggleSelected(task.id);
      return;
    }
    onTaskPress?.(task.id);
  };

  const handleTaskLongPress = useCallback((task: Task) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSelectedIds((prev) => {
      if (prev.has(task.id)) return prev;
      const next = new Set(prev);
      next.add(task.id);
      return next;
    });
  }, []);

  const handleBulkArchive = useCallback(() => {
    if (selectedIds.size === 0) return;
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    archiveMany(Array.from(selectedIds));
    exitSelection();
  }, [selectedIds, archiveMany, exitSelection]);

  // A mixed selection pins rather than unpins, so the action is only
  // destructive to existing pins once everything selected is already pinned.
  const bulkPinWouldPin = Array.from(selectedIds).some((id) => !isPinned(id));

  const handleBulkPin = useCallback(() => {
    if (selectedIds.size === 0) return;
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    for (const taskId of selectedIds) {
      if (isPinned(taskId) !== bulkPinWouldPin) continue;
      togglePin(taskId);
    }
    exitSelection();
  }, [selectedIds, isPinned, bulkPinWouldPin, togglePin, exitSelection]);

  const handleRefresh = async () => {
    await Promise.all([refetch(), refetchIntegrations()]);
  };

  const handleToggleGroup = useCallback(
    (groupKey: string) => {
      LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
      toggleGroupCollapsed(groupKey);
    },
    [toggleGroupCollapsed],
  );

  const collapsedGroupKeys = useMemo(
    () => new Set(collapsedGroups),
    [collapsedGroups],
  );

  const listItems = useMemo(
    () =>
      buildTaskListItems({
        tasks: tasks.filter((task) => !(task.id in archivedTasks)),
        organizeMode,
        sortMode,
        collapsedGroupKeys,
      }),
    [tasks, archivedTasks, organizeMode, sortMode, collapsedGroupKeys],
  );

  if (error) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <Text className="mb-4 text-center text-status-error">{error}</Text>
        <Pressable
          onPress={handleRefresh}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (integrationsError && tasks.length === 0) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <Text className="mb-4 text-center text-status-error">
          {integrationsError}
        </Text>
        <Pressable
          onPress={handleRefresh}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Retry</Text>
        </Pressable>
      </View>
    );
  }

  const isInitialLoading =
    (isLoading && tasks.length === 0) ||
    (tasks.length === 0 && hasGithubIntegration === null);

  if (isInitialLoading) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
        <Text className="mt-4 text-gray-11">Loading tasks...</Text>
      </View>
    );
  }

  const activeTaskCount = tasks.reduce(
    (count, task) => count + (task.id in archivedTasks ? 0 : 1),
    0,
  );

  if (hasGithubIntegration === false && activeTaskCount === 0) {
    return <GitHubConnectionPrompt mode="empty" onConnected={handleRefresh} />;
  }

  if (activeTaskCount === 0) {
    return <CreateTaskEmptyState onCreateTask={onCreateTask} />;
  }

  return (
    <View className="flex-1">
      <FlatList
        scrollEnabled={scrollEnabled}
        data={listItems}
        keyExtractor={(item) =>
          item.type === "task" ? item.task.id : item.groupKey
        }
        ListHeaderComponent={
          <>
            {listHeader}
            {integrationsError ? (
              <GitHubLoadNotice
                message={integrationsError}
                onRetry={handleRefresh}
              />
            ) : null}
          </>
        }
        renderItem={({ item }) => {
          if (item.type === "repo-header") {
            return (
              <GroupHeader
                label={item.repoLabel}
                count={item.count}
                collapsed={item.collapsed}
                onPress={() => handleToggleGroup(item.groupKey)}
                icon={<GitBranch size={14} color={themeColors.gray[10]} />}
              />
            );
          }

          if (item.type === "date-header") {
            return (
              <GroupHeader
                label={item.label}
                count={item.count}
                collapsed={item.collapsed}
                onPress={() => handleToggleGroup(item.groupKey)}
                uppercase
              />
            );
          }

          return (
            <SwipeableTaskItem
              task={item.task}
              isArchived={false}
              onPress={handleTaskPress}
              onArchive={archive}
              onUnarchive={unarchive}
              onLongPress={handleTaskLongPress}
              selectionMode={selectionMode}
              selected={selectedIds.has(item.task.id)}
              pinned={isPinned(item.task.id)}
              awaitingInput={awaitingInputTaskIds.has(item.task.id)}
              onSwipeStart={() => setScrollEnabled(false)}
              onSwipeEnd={() => setScrollEnabled(true)}
            />
          );
        }}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={handleRefresh}
            tintColor={themeColors.accent[9]}
          />
        }
        contentContainerStyle={{
          paddingTop: contentInsetTop,
          paddingBottom: 100,
        }}
      />

      {selectionMode ? (
        <View
          className="absolute inset-x-0 bottom-0 flex-row items-center gap-3 border-gray-6 border-t bg-card px-4 pt-3"
          style={{ paddingBottom: 28 }}
        >
          <Pressable
            onPress={exitSelection}
            hitSlop={8}
            className="h-10 w-10 items-center justify-center rounded-full bg-gray-3 active:bg-gray-4"
            accessibilityLabel="Cancel selection"
          >
            <X size={18} color={themeColors.gray[11]} weight="bold" />
          </Pressable>
          <Text
            className="flex-1 font-medium text-[15px] text-gray-12"
            numberOfLines={1}
          >
            {selectedIds.size} selected
          </Text>
          <Pressable
            onPress={handleBulkPin}
            className="flex-row items-center gap-2 rounded-full bg-gray-3 px-4 py-2.5 active:bg-gray-4"
            accessibilityLabel={
              bulkPinWouldPin ? "Pin selected tasks" : "Unpin selected tasks"
            }
          >
            {bulkPinWouldPin ? (
              <PushPin size={16} color={themeColors.gray[11]} weight="fill" />
            ) : (
              <PushPinSlash
                size={16}
                color={themeColors.gray[11]}
                weight="fill"
              />
            )}
            <Text className="font-semibold text-[14px] text-gray-12">
              {bulkPinWouldPin ? "Pin" : "Unpin"}
            </Text>
          </Pressable>
          <Pressable
            onPress={handleBulkArchive}
            className="flex-row items-center gap-2 rounded-full px-4 py-2.5 active:opacity-80"
            style={{ backgroundColor: themeColors.accent[9] }}
            accessibilityLabel="Archive selected tasks"
          >
            <Archive
              size={16}
              color={themeColors.accent.contrast}
              weight="fill"
            />
            <Text className="font-semibold text-[14px] text-accent-contrast">
              Archive
            </Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}
