import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import { Archive, GitBranch, Plus, Sparkle, X } from "phosphor-react-native";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useTasks } from "../hooks/useTasks";
import { useUserIntegrations } from "../hooks/useUserIntegrations";
import { useArchivedTasksStore } from "../stores/archivedTasksStore";
import { taskActivityTimestamp, useTaskStore } from "../stores/taskStore";
import type { Task } from "../types";
import { GitHubConnectionPrompt } from "./GitHubConnectionPrompt";
import { GitHubLoadNotice } from "./GitHubLoadNotice";
import { SwipeableTaskItem } from "./SwipeableTaskItem";

interface TaskListProps {
  onTaskPress?: (taskId: string) => void;
  onCreateTask?: () => void;
  /** Top inset so the list can scroll behind a floating header. */
  contentInsetTop?: number;
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

type ListItem =
  | { type: "task"; task: Task }
  | { type: "repo-header"; repoLabel: string; count: number }
  | { type: "date-header"; label: string; count: number };

const NO_REPO_LABEL = "No repository";

function relativeDateGroup(ms: number): string {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const startOfDate = new Date(ms);
  startOfDate.setHours(0, 0, 0, 0);
  const days = Math.round(
    (startOfToday.getTime() - startOfDate.getTime()) / 86_400_000,
  );
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  if (days < 30) return "This month";
  return "Earlier";
}

const DATE_GROUP_ORDER = [
  "Today",
  "Yesterday",
  "This week",
  "This month",
  "Earlier",
];

export function TaskList({
  onTaskPress,
  onCreateTask,
  contentInsetTop = 0,
}: TaskListProps) {
  const { tasks, isLoading, error, refetch } = useTasks({
    originProduct: "user_created",
  });
  const {
    error: integrationsError,
    hasGithubIntegration,
    refetch: refetchIntegrations,
  } = useUserIntegrations();
  const themeColors = useThemeColors();
  const { archivedTasks, archive, archiveMany, unarchive } =
    useArchivedTasksStore();
  const organizeMode = useTaskStore((s) => s.organizeMode);
  const sortMode = useTaskStore((s) => s.sortMode);
  const [scrollEnabled, setScrollEnabled] = useState(true);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const selectionMode = selectedIds.size > 0;

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

  const handleRefresh = async () => {
    await Promise.all([refetch(), refetchIntegrations()]);
  };

  const listItems = useMemo((): ListItem[] => {
    const active = tasks.filter((task) => !(task.id in archivedTasks));
    const items: ListItem[] = [];

    if (organizeMode === "by-project") {
      const groups = new Map<string, Task[]>();
      for (const task of active) {
        const key = task.repository?.trim() || NO_REPO_LABEL;
        const bucket = groups.get(key);
        if (bucket) {
          bucket.push(task);
        } else {
          groups.set(key, [task]);
        }
      }

      for (const tasksInRepo of groups.values()) {
        tasksInRepo.sort(
          (a, b) =>
            taskActivityTimestamp(b, sortMode) -
            taskActivityTimestamp(a, sortMode),
        );
      }

      const groupEntries = Array.from(groups.entries()).sort((a, b) => {
        if (a[0] === NO_REPO_LABEL) return 1;
        if (b[0] === NO_REPO_LABEL) return -1;
        return (
          taskActivityTimestamp(b[1][0], sortMode) -
          taskActivityTimestamp(a[1][0], sortMode)
        );
      });

      for (const [repoLabel, tasksInRepo] of groupEntries) {
        items.push({
          type: "repo-header",
          repoLabel,
          count: tasksInRepo.length,
        });
        for (const task of tasksInRepo) {
          items.push({ type: "task", task });
        }
      }
    } else {
      const sorted = [...active].sort(
        (a, b) =>
          taskActivityTimestamp(b, sortMode) -
          taskActivityTimestamp(a, sortMode),
      );

      const buckets = new Map<string, Task[]>();
      for (const task of sorted) {
        const label = relativeDateGroup(taskActivityTimestamp(task, sortMode));
        const bucket = buckets.get(label);
        if (bucket) {
          bucket.push(task);
        } else {
          buckets.set(label, [task]);
        }
      }

      for (const label of DATE_GROUP_ORDER) {
        const bucket = buckets.get(label);
        if (!bucket || bucket.length === 0) continue;
        items.push({ type: "date-header", label, count: bucket.length });
        for (const task of bucket) {
          items.push({ type: "task", task });
        }
      }
    }

    return items;
  }, [tasks, archivedTasks, organizeMode, sortMode]);

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
        keyExtractor={(item) => {
          switch (item.type) {
            case "repo-header":
              return `__repo__${item.repoLabel}`;
            case "date-header":
              return `__date__${item.label}`;
            case "task":
              return item.task.id;
          }
        }}
        ListHeaderComponent={
          integrationsError ? (
            <GitHubLoadNotice
              message={integrationsError}
              onRetry={handleRefresh}
            />
          ) : null
        }
        renderItem={({ item }) => {
          if (item.type === "repo-header") {
            return (
              <View className="flex-row items-center gap-2 bg-gray-2 px-3 py-2">
                <GitBranch size={14} color={themeColors.gray[10]} />
                <Text
                  className="flex-1 font-medium text-[12px] text-gray-11"
                  numberOfLines={1}
                >
                  {item.repoLabel}
                </Text>
                <Text className="text-[11px] text-gray-9">{item.count}</Text>
              </View>
            );
          }

          if (item.type === "date-header") {
            return (
              <View className="flex-row items-center gap-2 bg-gray-2 px-3 py-2">
                <Text
                  className="flex-1 font-medium text-[12px] text-gray-11 uppercase"
                  style={{ letterSpacing: 0.5 }}
                  numberOfLines={1}
                >
                  {item.label}
                </Text>
                <Text className="text-[11px] text-gray-9">{item.count}</Text>
              </View>
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
