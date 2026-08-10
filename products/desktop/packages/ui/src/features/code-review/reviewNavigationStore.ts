import { create } from "zustand";
import type { CommentFileFilter } from "./commentFileFilter";

export type ReviewMode = "closed" | "split" | "expanded";

interface ReviewNavigationStoreState {
  activeFilePaths: Record<string, string | null>;
  scrollRequests: Record<string, string | null>;
  reviewModes: Record<string, ReviewMode>;
  selectedPrUrls: Record<string, string | undefined>;
  commentFileFilters: Record<string, CommentFileFilter>;
  hideViewedFiles: Record<string, boolean>;
}

interface ReviewNavigationStoreActions {
  setActiveFilePath: (taskId: string, path: string | null) => void;
  requestScrollToFile: (taskId: string, path: string) => void;
  clearScrollRequest: (taskId: string) => void;
  clearTask: (taskId: string) => void;
  setReviewMode: (taskId: string, mode: ReviewMode) => void;
  setSelectedPrUrl: (taskId: string, url: string) => void;
  setCommentFileFilter: (taskId: string, filter: CommentFileFilter) => void;
  setHideViewedFiles: (taskId: string, hideViewed: boolean) => void;
  getReviewMode: (taskId: string) => ReviewMode;
}

type ReviewNavigationStore = ReviewNavigationStoreState &
  ReviewNavigationStoreActions;

export const useReviewNavigationStore = create<ReviewNavigationStore>()(
  (set, get) => ({
    activeFilePaths: {},
    scrollRequests: {},
    reviewModes: {},
    selectedPrUrls: {},
    commentFileFilters: {},
    hideViewedFiles: {},

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
        hideViewedFiles: { ...state.hideViewedFiles, [taskId]: false },
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
        selectedPrUrls: { ...state.selectedPrUrls, [taskId]: undefined },
        hideViewedFiles: { ...state.hideViewedFiles, [taskId]: false },
      })),

    setReviewMode: (taskId, mode) =>
      set((state) => ({
        reviewModes: { ...state.reviewModes, [taskId]: mode },
        // A row-selected historical PR only applies to this review visit.
        // Closing restores the task's normal primary-PR resolution.
        selectedPrUrls:
          mode === "closed"
            ? { ...state.selectedPrUrls, [taskId]: undefined }
            : state.selectedPrUrls,
      })),

    setSelectedPrUrl: (taskId, url) =>
      set((state) => ({
        selectedPrUrls: { ...state.selectedPrUrls, [taskId]: url },
      })),

    setCommentFileFilter: (taskId, filter) =>
      set((state) => ({
        commentFileFilters: {
          ...state.commentFileFilters,
          [taskId]: filter,
        },
      })),

    setHideViewedFiles: (taskId, hideViewed) =>
      set((state) => ({
        hideViewedFiles: {
          ...state.hideViewedFiles,
          [taskId]: hideViewed,
        },
      })),

    getReviewMode: (taskId) => get().reviewModes[taskId] ?? "closed",
  }),
);
