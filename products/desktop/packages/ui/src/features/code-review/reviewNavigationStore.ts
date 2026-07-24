import { create } from "zustand";
import type { CommentFileFilter } from "./commentFileFilter";

export type ReviewMode = "closed" | "split" | "expanded";

interface ReviewNavigationStoreState {
  activeFilePaths: Record<string, string | null>;
  scrollRequests: Record<string, string | null>;
  reviewModes: Record<string, ReviewMode>;
  commentFileFilters: Record<string, CommentFileFilter>;
}

interface ReviewNavigationStoreActions {
  setActiveFilePath: (taskId: string, path: string | null) => void;
  requestScrollToFile: (taskId: string, path: string) => void;
  clearScrollRequest: (taskId: string) => void;
  clearTask: (taskId: string) => void;
  setReviewMode: (taskId: string, mode: ReviewMode) => void;
  setCommentFileFilter: (taskId: string, filter: CommentFileFilter) => void;
  getReviewMode: (taskId: string) => ReviewMode;
}

type ReviewNavigationStore = ReviewNavigationStoreState &
  ReviewNavigationStoreActions;

export const useReviewNavigationStore = create<ReviewNavigationStore>()(
  (set, get) => ({
    activeFilePaths: {},
    scrollRequests: {},
    reviewModes: {},
    commentFileFilters: {},

    setActiveFilePath: (taskId, path) =>
      set((state) => ({
        activeFilePaths: { ...state.activeFilePaths, [taskId]: path },
      })),

    requestScrollToFile: (taskId, path) =>
      set((state) => ({
        scrollRequests: { ...state.scrollRequests, [taskId]: path },
        commentFileFilters: {
          ...state.commentFileFilters,
          [taskId]: "none",
        },
      })),

    clearScrollRequest: (taskId) =>
      set((state) => ({
        scrollRequests: { ...state.scrollRequests, [taskId]: null },
      })),

    clearTask: (taskId) =>
      set((state) => ({
        activeFilePaths: { ...state.activeFilePaths, [taskId]: null },
        scrollRequests: { ...state.scrollRequests, [taskId]: null },
        commentFileFilters: {
          ...state.commentFileFilters,
          [taskId]: "none",
        },
      })),

    setReviewMode: (taskId, mode) =>
      set((state) => ({
        reviewModes: { ...state.reviewModes, [taskId]: mode },
      })),

    setCommentFileFilter: (taskId, filter) =>
      set((state) => ({
        commentFileFilters: {
          ...state.commentFileFilters,
          [taskId]: filter,
        },
      })),

    getReviewMode: (taskId) => get().reviewModes[taskId] ?? "closed",
  }),
);
