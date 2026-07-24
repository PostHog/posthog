import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import { ArrowCounterClockwise } from "phosphor-react-native";
import { useEffect, useRef } from "react";
import {
  Animated,
  Easing,
  LayoutAnimation,
  PanResponder,
  Pressable,
  View,
} from "react-native";
import { TaskStatusIcon } from "@/features/tasks/components/TaskStatusIcon";
import type { Task } from "@/features/tasks/types";
import { useThemeColors } from "@/lib/theme";

const SWIPE_THRESHOLD = 60;

interface SwipeableArchivedDrawerRowProps {
  task: Task;
  active: boolean;
  onPress: (taskId: string) => void;
  onUnarchive: (taskId: string) => void;
}

export function SwipeableArchivedDrawerRow({
  task,
  active,
  onPress,
  onUnarchive,
}: SwipeableArchivedDrawerRowProps) {
  const themeColors = useThemeColors();
  const translateX = useRef(new Animated.Value(0)).current;
  const actionTriggeredRef = useRef(false);

  const propsRef = useRef({ task, onUnarchive });
  propsRef.current = { task, onUnarchive };

  useEffect(() => {
    translateX.setValue(0);
    actionTriggeredRef.current = false;
  }, [translateX]);

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => false,
      onMoveShouldSetPanResponder: (_, gesture) =>
        Math.abs(gesture.dx) > 5 &&
        Math.abs(gesture.dx) > Math.abs(gesture.dy) &&
        gesture.dx < 0,
      onMoveShouldSetPanResponderCapture: (_, gesture) =>
        Math.abs(gesture.dx) > 8 &&
        Math.abs(gesture.dx) > Math.abs(gesture.dy * 1.2) &&
        gesture.dx < 0,
      onPanResponderTerminationRequest: () => false,
      onShouldBlockNativeResponder: () => true,
      onPanResponderGrant: () => {
        actionTriggeredRef.current = false;
      },
      onPanResponderMove: (_, gesture) => {
        translateX.setValue(gesture.dx > 0 ? 0 : gesture.dx);
      },
      onPanResponderRelease: (_, gesture) => {
        const p = propsRef.current;
        if (gesture.dx < -SWIPE_THRESHOLD && !actionTriggeredRef.current) {
          actionTriggeredRef.current = true;
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
          Animated.timing(translateX, {
            toValue: -400,
            duration: 150,
            easing: Easing.in(Easing.ease),
            useNativeDriver: true,
          }).start(() => {
            LayoutAnimation.configureNext(
              LayoutAnimation.Presets.easeInEaseOut,
            );
            p.onUnarchive(p.task.id);
          });
        } else {
          Animated.spring(translateX, {
            toValue: 0,
            useNativeDriver: true,
            tension: 40,
            friction: 8,
          }).start();
        }
      },
      onPanResponderTerminate: () => {
        Animated.spring(translateX, {
          toValue: 0,
          useNativeDriver: true,
        }).start();
      },
    }),
  ).current;

  return (
    <View className="overflow-hidden">
      <View
        className="absolute inset-y-0 right-0 left-0 flex-row items-center justify-end px-4"
        style={{ backgroundColor: themeColors.accent[9] }}
      >
        <ArrowCounterClockwise size={16} color="#fff" />
        <Text className="ml-1.5 font-medium text-white text-xs">Unarchive</Text>
      </View>

      <Animated.View
        style={{
          transform: [{ translateX }],
          backgroundColor: themeColors.background,
        }}
        {...panResponder.panHandlers}
      >
        <Pressable
          onPress={() => onPress(task.id)}
          className={`flex-row items-center gap-3 rounded-md px-3 py-2.5 ${active ? "bg-gray-3" : "active:bg-gray-2"}`}
        >
          <View className="h-5 w-5 shrink-0 items-center justify-center">
            <TaskStatusIcon task={task} size={16} />
          </View>
          <Text
            className="flex-1 text-[15px] text-gray-10"
            numberOfLines={1}
            ellipsizeMode="tail"
          >
            {task.title}
          </Text>
        </Pressable>
      </Animated.View>
    </View>
  );
}
