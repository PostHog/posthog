import * as Haptics from "expo-haptics";
import { Archive, ArrowCounterClockwise } from "phosphor-react-native";
import { useEffect, useRef } from "react";
import {
  Animated,
  Easing,
  LayoutAnimation,
  PanResponder,
  Text,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { Task } from "../types";
import {
  confirmArchiveRunningTask,
  isTaskRunning,
} from "../utils/archiveGuard";
import { TaskItem } from "./TaskItem";

const SWIPE_THRESHOLD = 60;

function springToRest(value: Animated.Value): void {
  Animated.spring(value, {
    toValue: 0,
    useNativeDriver: true,
    tension: 40,
    friction: 8,
  }).start();
}

// Slide the row off-screen, then smooth the list-height change before running
// the archive/unarchive side effect.
function slideOut(value: Animated.Value, onDone: () => void): void {
  Animated.timing(value, {
    toValue: -400,
    duration: 150,
    easing: Easing.in(Easing.ease),
    useNativeDriver: true,
  }).start(() => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    onDone();
  });
}

interface SwipeableTaskItemProps {
  task: Task;
  isArchived: boolean;
  onPress: (task: Task) => void;
  onArchive: (taskId: string) => void;
  onUnarchive: (taskId: string) => void;
  onLongPress?: (task: Task) => void;
  selectionMode?: boolean;
  selected?: boolean;
  onSwipeStart?: () => void;
  onSwipeEnd?: () => void;
}

export function SwipeableTaskItem({
  task,
  isArchived,
  onPress,
  onArchive,
  onUnarchive,
  onLongPress,
  selectionMode = false,
  selected = false,
  onSwipeStart,
  onSwipeEnd,
}: SwipeableTaskItemProps) {
  const themeColors = useThemeColors();
  const translateX = useRef(new Animated.Value(0)).current;
  const actionTriggeredRef = useRef(false);

  // PanResponder.create runs once per mount, so its callbacks close over the
  // *initial* prop values. Route through a ref so props stay current without
  // rebuilding the responder.
  const propsRef = useRef({
    task,
    isArchived,
    onArchive,
    onUnarchive,
    selectionMode,
    onSwipeStart,
    onSwipeEnd,
  });
  propsRef.current = {
    task,
    isArchived,
    onArchive,
    onUnarchive,
    selectionMode,
    onSwipeStart,
    onSwipeEnd,
  };

  // Reset position when the item reappears (e.g. moved between sections)
  useEffect(() => {
    translateX.setValue(0);
    actionTriggeredRef.current = false;
  }, [translateX]);

  const panResponder = useRef(
    PanResponder.create({
      // Start tracking immediately on horizontal movement
      onStartShouldSetPanResponder: () => false,
      onMoveShouldSetPanResponder: (_, gesture) =>
        !propsRef.current.selectionMode &&
        Math.abs(gesture.dx) > 5 &&
        Math.abs(gesture.dx) > Math.abs(gesture.dy) &&
        gesture.dx < 0,
      // Capture before children so FlatList doesn't steal
      onMoveShouldSetPanResponderCapture: (_, gesture) =>
        !propsRef.current.selectionMode &&
        Math.abs(gesture.dx) > 8 &&
        Math.abs(gesture.dx) > Math.abs(gesture.dy * 1.2) &&
        gesture.dx < 0,
      // Never let go once we have the gesture
      onPanResponderTerminationRequest: () => false,
      onShouldBlockNativeResponder: () => true,
      onPanResponderGrant: () => {
        actionTriggeredRef.current = false;
        propsRef.current.onSwipeStart?.();
      },
      onPanResponderMove: (_, gesture) => {
        // Clamp to left-only swipe
        translateX.setValue(gesture.dx > 0 ? 0 : gesture.dx);
      },
      onPanResponderRelease: (_, gesture) => {
        const p = propsRef.current;
        p.onSwipeEnd?.();
        if (gesture.dx < -SWIPE_THRESHOLD && !actionTriggeredRef.current) {
          actionTriggeredRef.current = true;
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

          // Archiving a running task stops its agent, so spring the row back
          // and confirm first — only slide out and archive once the user
          // agrees, matching the animation of every other archive action.
          if (!p.isArchived && isTaskRunning(p.task)) {
            springToRest(translateX);
            confirmArchiveRunningTask(p.task.title, () =>
              slideOut(translateX, () => p.onArchive(p.task.id)),
            );
            return;
          }

          slideOut(translateX, () => {
            if (p.isArchived) {
              p.onUnarchive(p.task.id);
            } else {
              p.onArchive(p.task.id);
            }
          });
        } else {
          springToRest(translateX);
        }
      },
      onPanResponderTerminate: () => {
        propsRef.current.onSwipeEnd?.();
        Animated.spring(translateX, {
          toValue: 0,
          useNativeDriver: true,
        }).start();
      },
    }),
  ).current;

  const actionBg = isArchived ? themeColors.accent[9] : themeColors.gray[8];
  const ActionIcon = isArchived ? ArrowCounterClockwise : Archive;
  const actionLabel = isArchived ? "Restore" : "Archive";

  return (
    <View className="overflow-hidden">
      {/* Action revealed behind the row */}
      <View
        className="absolute inset-y-0 right-0 left-0 flex-row items-center justify-end px-5"
        style={{ backgroundColor: actionBg }}
      >
        <ActionIcon size={18} color="#fff" />
        <Text className="ml-2 font-medium text-white text-xs">
          {actionLabel}
        </Text>
      </View>

      {/* Sliding task row */}
      <Animated.View
        style={{
          transform: [{ translateX }],
          backgroundColor: themeColors.background,
        }}
        {...panResponder.panHandlers}
      >
        <TaskItem
          task={task}
          onPress={onPress}
          onLongPress={onLongPress}
          selectionMode={selectionMode}
          selected={selected}
        />
      </Animated.View>
    </View>
  );
}
