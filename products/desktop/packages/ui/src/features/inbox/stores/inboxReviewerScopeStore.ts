import {
  INBOX_SCOPE_FOR_YOU,
  type InboxScope,
} from "@posthog/core/inbox/reportMembership";
import { create } from "zustand";

interface InboxReviewerScopeStore {
  scope: InboxScope;
  setScope: (scope: InboxScope) => void;
}

export const useInboxReviewerScopeStore = create<InboxReviewerScopeStore>(
  (set) => ({
    scope: INBOX_SCOPE_FOR_YOU,
    setScope: (scope) => set({ scope }),
  }),
);
