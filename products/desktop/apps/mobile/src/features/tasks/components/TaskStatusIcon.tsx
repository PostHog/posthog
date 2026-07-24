import {
  ChatCircle,
  CheckCircle,
  CircleIcon,
  CircleNotch,
  GitPullRequest,
  XCircle,
} from "phosphor-react-native";
import { memo, useEffect, useRef } from "react";
import { Animated, Easing } from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { Task } from "../types";
import { getTaskStatusIconKind } from "./taskStatusIconKind";

interface TaskStatusIconProps {
  task: Task;
  size?: number;
}

function TaskStatusIconComponent({ task, size = 16 }: TaskStatusIconProps) {
  const colors = useThemeColors();
  const iconKind = getTaskStatusIconKind(task);

  const rotation = useRef(new Animated.Value(0)).current;
  const isRunning = iconKind === "running";

  useEffect(() => {
    if (!isRunning) {
      rotation.stopAnimation();
      rotation.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.timing(rotation, {
        toValue: 1,
        duration: 1000,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [isRunning, rotation]);

  if (iconKind === "pr") {
    return (
      <GitPullRequest size={size} weight="bold" color={colors.status.success} />
    );
  }

  if (iconKind === "completed") {
    return (
      <CheckCircle size={size} weight="fill" color={colors.status.success} />
    );
  }

  if (iconKind === "failed") {
    return <XCircle size={size} weight="fill" color={colors.status.error} />;
  }

  if (iconKind === "running") {
    const spin = rotation.interpolate({
      inputRange: [0, 1],
      outputRange: ["0deg", "360deg"],
    });
    return (
      <Animated.View style={{ transform: [{ rotate: spin }] }}>
        <CircleNotch size={size} weight="bold" color={colors.accent[9]} />
      </Animated.View>
    );
  }

  if (iconKind === "started") {
    return <CircleIcon size={size} weight="duotone" color={colors.accent[9]} />;
  }

  return <ChatCircle size={size} weight="regular" color={colors.gray[9]} />;
}

export const TaskStatusIcon = memo(TaskStatusIconComponent);
