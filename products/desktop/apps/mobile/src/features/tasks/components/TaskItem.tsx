import { Text } from "@components/text";
import { xmlToPlainText } from "@posthog/core/message-editor/content";
import type { Task } from "@posthog/shared";
import { differenceInHours, format, formatDistanceToNow } from "date-fns";
import {
  Check,
  GitMerge,
  GitPullRequest,
  Laptop,
  PushPin,
} from "phosphor-react-native";
import { memo } from "react";
import { Pressable, View } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { type ThemeColors, useThemeColors } from "@/lib/theme";
import { usePrStatus } from "../hooks/usePrStatus";
import {
  deriveTaskPrChip,
  getPrChipAppearance,
  MERGED_PR_COLOR,
  type PrChipTone,
  prChipAccessibilityLabel,
  type TaskPrChip,
} from "../utils/prPresentation";
import { isLocalRunTask } from "../utils/taskRunPlacement";
import { TaskStatusIcon } from "./TaskStatusIcon";

// Tone -> row styling. Kept here rather than in the pure helper: `getPrVisualConfig`
// speaks in desktop's color names, and only this layer knows the RN tokens.
function prChipStyle(
  tone: PrChipTone,
  themeColors: ThemeColors,
): { textClassName: string; color: string } {
  switch (tone) {
    case "green":
      return {
        textClassName: "text-status-success",
        color: themeColors.status.success,
      };
    case "red":
      return {
        textClassName: "text-status-error",
        color: themeColors.status.error,
      };
    case "purple":
      return { textClassName: "text-[#8e4ec6]", color: MERGED_PR_COLOR };
    case "gray":
      return { textClassName: "text-gray-11", color: themeColors.gray[11] };
  }
}

/**
 * Tappable PR shortcut on a task row. Nested inside the row's Pressable: React
 * Native hands the touch to the innermost responder, so tapping the chip opens
 * GitHub without also navigating into the task, and a long-press anywhere else
 * on the row still starts multi-select.
 */
function PrChip({ chip }: { chip: TaskPrChip }) {
  const themeColors = useThemeColors();
  const { data: status } = usePrStatus(chip.url);
  const { tone, statusLabel } = getPrChipAppearance(status);
  const { textClassName, color } = prChipStyle(tone, themeColors);
  const Icon = tone === "purple" ? GitMerge : GitPullRequest;

  return (
    <Pressable
      onPress={() => openExternalUrl(chip.url)}
      hitSlop={8}
      className="shrink-0 flex-row items-center gap-0.5 rounded border border-gray-6 bg-gray-3 px-1.5 py-0.5 active:opacity-60"
      accessibilityRole="link"
      accessibilityLabel={prChipAccessibilityLabel(chip, statusLabel)}
    >
      <Icon size={11} weight="bold" color={color} />
      <Text className={`text-[11px] ${textClassName}`}>{chip.label}</Text>
    </Pressable>
  );
}

interface TaskItemProps {
  task: Task;
  onPress: (task: Task) => void;
  onLongPress?: (task: Task) => void;
  selectionMode?: boolean;
  selected?: boolean;
  pinned?: boolean;
  /** The agent is blocked on this task's user — emphasized in the list. */
  awaitingInput?: boolean;
}

function TaskItemComponent({
  task,
  onPress,
  onLongPress,
  selectionMode = false,
  selected = false,
  pinned = false,
  awaitingInput = false,
}: TaskItemProps) {
  const themeColors = useThemeColors();
  const createdAt = new Date(task.created_at);
  const hoursSinceCreated = differenceInHours(new Date(), createdAt);
  const timeDisplay =
    hoursSinceCreated < 24
      ? formatDistanceToNow(createdAt, { addSuffix: true })
      : format(createdAt, "MMM d");
  const prChip = deriveTaskPrChip(task);
  // Desktop-local runs are listed but can't be driven from here until they're
  // continued in the cloud — the glyph plus the dimmed title says so without
  // spending a whole row on an explanation.
  const isLocalRun = isLocalRunTask(task);

  return (
    <Pressable
      onPress={() => onPress(task)}
      onLongPress={onLongPress ? () => onLongPress(task) : undefined}
      delayLongPress={300}
      className={`flex-row items-start gap-3 border-gray-6 border-b px-3 py-3 ${selected ? "bg-accent-3" : "active:bg-gray-3"}`}
    >
      {/* Status icon column (or selection checkbox in selection mode) */}
      <View className="mt-0.5 h-5 w-5 shrink-0 items-center justify-center">
        {selectionMode ? (
          <View
            className={`h-5 w-5 items-center justify-center rounded-full border ${selected ? "border-transparent" : "border-gray-7"}`}
            style={selected ? { backgroundColor: themeColors.accent[9] } : null}
          >
            {selected ? <Check size={12} color="#fff" weight="bold" /> : null}
          </View>
        ) : (
          <TaskStatusIcon task={task} size={16} />
        )}
      </View>

      {/* Content column */}
      <View className="min-w-0 flex-1">
        <View className="flex-row items-center gap-2">
          {awaitingInput ? (
            <View
              className="h-1.5 w-1.5 shrink-0 rounded-full"
              style={{ backgroundColor: themeColors.accent[9] }}
              accessibilityLabel="Waiting on you"
            />
          ) : null}
          {isLocalRun ? (
            <View className="shrink-0" accessibilityLabel="Ran on your desktop">
              <Laptop size={12} weight="bold" color={themeColors.gray[9]} />
            </View>
          ) : null}
          <Text
            className={`flex-1 text-[14px] ${isLocalRun ? "text-gray-10" : "text-gray-12"} ${awaitingInput ? "font-bold" : "font-medium"}`}
            numberOfLines={1}
            ellipsizeMode="tail"
          >
            {task.title}
          </Text>
          {pinned ? (
            <PushPin size={11} weight="fill" color={themeColors.gray[9]} />
          ) : null}
          {prChip ? (
            <PrChip chip={prChip} />
          ) : (
            <Text className="shrink-0 text-[11px] text-gray-9">
              {timeDisplay}
            </Text>
          )}
        </View>

        {task.description ? (
          <Text
            className="mt-0.5 text-[12px] text-gray-10"
            numberOfLines={2}
            ellipsizeMode="tail"
          >
            {xmlToPlainText(task.description)}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

export const TaskItem = memo(TaskItemComponent);
