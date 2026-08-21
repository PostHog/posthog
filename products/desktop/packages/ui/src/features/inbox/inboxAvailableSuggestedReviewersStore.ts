import type { AvailableSuggestedReviewer } from "@posthog/shared";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AvailableSuggestedReviewersCacheEntry {
  reviewers: AvailableSuggestedReviewer[];
  fetchedAt: number;
}

interface InboxAvailableSuggestedReviewersStoreState {
  byAuthIdentity: Record<string, AvailableSuggestedReviewersCacheEntry>;
}

interface InboxAvailableSuggestedReviewersStoreActions {
  setReviewersForAuthIdentity: (
    authIdentity: string,
    reviewers: AvailableSuggestedReviewer[],
  ) => void;
  clearReviewersForAuthIdentity: (authIdentity: string) => void;
  getReviewersForAuthIdentity: (
    authIdentity: string | null | undefined,
  ) => AvailableSuggestedReviewersCacheEntry | null;
}

type InboxAvailableSuggestedReviewersStore =
  InboxAvailableSuggestedReviewersStoreState &
    InboxAvailableSuggestedReviewersStoreActions;

export const useInboxAvailableSuggestedReviewersStore =
  create<InboxAvailableSuggestedReviewersStore>()(
    persist(
      (set, get) => ({
        byAuthIdentity: {},

        setReviewersForAuthIdentity: (authIdentity, reviewers) =>
          set((state) => ({
            byAuthIdentity: {
              ...state.byAuthIdentity,
              [authIdentity]: {
                reviewers,
                fetchedAt: Date.now(),
              },
            },
          })),

        clearReviewersForAuthIdentity: (authIdentity) =>
          set((state) => {
            const next = { ...state.byAuthIdentity };
            delete next[authIdentity];
            return { byAuthIdentity: next };
          }),

        getReviewersForAuthIdentity: (authIdentity) => {
          if (!authIdentity) {
            return null;
          }
          return get().byAuthIdentity[authIdentity] ?? null;
        },
      }),
      {
        name: "inbox-available-suggested-reviewers-storage",
        partialize: (state) => ({
          byAuthIdentity: state.byAuthIdentity,
        }),
      },
    ),
  );
