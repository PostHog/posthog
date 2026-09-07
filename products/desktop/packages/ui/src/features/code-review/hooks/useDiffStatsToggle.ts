import type { Task } from "@posthog/shared/domain-types";
import { useCallback } from "react";
import { getDefaultReviewMode } from "../getDefaultReviewMode";
import { useReviewNavigationStore } from "../reviewNavigationStore";
import { useTaskDiffSummaryStats } from "./useTaskDiffSummaryStats";

interface DiffStatsToggleResult {
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
  hasChanges: boolean;
  isOpen: boolean;
  toggle: () => void;
}

export function useDiffStatsToggle(task: Task): DiffStatsToggleResult {
  const taskId = task.id;
  const { filesChanged, linesAdded, linesRemoved } =
    useTaskDiffSummaryStats(task);

  const reviewMode = useReviewNavigationStore(
    (s) => s.reviewModes[taskId] ?? "closed",
  );
  const setReviewMode = useReviewNavigationStore((s) => s.setReviewMode);

  const isOpen = reviewMode !== "closed";
  const toggle = useCallback(
    () => setReviewMode(taskId, isOpen ? "closed" : getDefaultReviewMode()),
    [setReviewMode, taskId, isOpen],
  );

  return {
    filesChanged,
    linesAdded,
    linesRemoved,
    hasChanges: filesChanged > 0,
    isOpen,
    toggle,
  };
}
