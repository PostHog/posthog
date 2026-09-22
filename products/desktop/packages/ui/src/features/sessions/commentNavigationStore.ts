import {
  type CommentTarget,
  commentTargetKey,
} from "@posthog/core/comments/anchors";
import type { HighlightResolution } from "@posthog/ui/features/sessions/components/commentViewTypes";
import { create } from "zustand";

type CommentFocusIntent = "navigate" | "reveal-thread" | "focus-only";

/** Which thread the task's comment surfaces are pointed at right now. */
type CommentFocus = {
  target: CommentTarget;
  threadId: string;
  /** Bumped on every request so re-picking the same thread scrolls again.
   *  A consumer that acts on focus takes each nonce once, and takes it only
   *  once it can act — returning without taking leaves the request to apply
   *  when the consumer is ready. */
  nonce: number;
  openCommentsTab: boolean;
  intent: CommentFocusIntent;
};

interface CommentNavigationStoreState {
  focusByTask: Record<string, CommentFocus | null>;
  /** targetKey → threadId → resolution. Only a surface that has rendered can
   *  know this, so a missing entry means unknown, not "exact". */
  resolutionsByTarget: Record<string, Map<string, HighlightResolution>>;
}

interface CommentNavigationStoreActions {
  requestCommentFocus: (
    taskId: string,
    target: CommentTarget,
    threadId: string,
    options?: { intent?: CommentFocusIntent },
  ) => void;
  setCommentResolutions: (
    target: CommentTarget,
    resolutions: Map<string, HighlightResolution>,
  ) => void;
  acknowledgeCommentsTabOpen: (taskId: string, nonce: number) => void;
}

type CommentNavigationStore = CommentNavigationStoreState &
  CommentNavigationStoreActions;

let nonce = 0;

function sameResolutions(
  current: Map<string, HighlightResolution> | undefined,
  next: Map<string, HighlightResolution>,
): boolean {
  if (!current || current.size !== next.size) return false;
  for (const [id, resolution] of next) {
    if (current.get(id) !== resolution) return false;
  }
  return true;
}

/**
 * The comment list (a tab in the activity sidebar) and the artifact surfaces (a
 * tab in the panel layout) live in sibling React trees, so neither can reach
 * the other's scroller. This store is the channel between them: the list writes
 * a focus request and the surface locates the anchor, and vice versa.
 *
 * Focus is durable state rather than a consumed event, because an artifact tab
 * may mount after the request is made and its comments arrive later still.
 */
export const useCommentNavigationStore = create<CommentNavigationStore>()(
  (set) => ({
    focusByTask: {},
    resolutionsByTarget: {},

    requestCommentFocus: (taskId, target, threadId, options) => {
      nonce += 1;
      set((state) => ({
        focusByTask: {
          ...state.focusByTask,
          [taskId]: {
            target,
            threadId,
            nonce,
            openCommentsTab: true,
            intent: options?.intent ?? "navigate",
          },
        },
      }));
    },

    // The surfaces recompute anchors on every scroll and resize, so an
    // unchanged result must not become a store write the whole list re-renders on.
    acknowledgeCommentsTabOpen: (taskId, acknowledgedNonce) =>
      set((state) => {
        const focus = state.focusByTask[taskId];
        if (
          !focus ||
          focus.nonce !== acknowledgedNonce ||
          !focus.openCommentsTab
        )
          return state;
        return {
          focusByTask: {
            ...state.focusByTask,
            [taskId]: { ...focus, openCommentsTab: false },
          },
        };
      }),

    setCommentResolutions: (target, resolutions) =>
      set((state) => {
        const key = commentTargetKey(target);
        if (sameResolutions(state.resolutionsByTarget[key], resolutions)) {
          return state;
        }
        return {
          resolutionsByTarget: {
            ...state.resolutionsByTarget,
            [key]: resolutions,
          },
        };
      }),
  }),
);
