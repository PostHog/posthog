import type {
  DismissalReasonOptionValue,
  ResolveReasonOptionValue,
} from "@posthog/shared/dismissalReasons";
import { create } from "zustand";

export interface InboxReportActionDraft<Reason> {
  reason: Reason;
  note: string;
  reopen: boolean;
}

interface InboxReportActionDraftState {
  generation: number;
  dismiss: Record<
    string,
    InboxReportActionDraft<DismissalReasonOptionValue> | undefined
  >;
  resolve: Record<
    string,
    InboxReportActionDraft<ResolveReasonOptionValue> | undefined
  >;
  setDismiss: (
    generation: number,
    reportId: string,
    draft: InboxReportActionDraft<DismissalReasonOptionValue> | undefined,
  ) => void;
  setResolve: (
    generation: number,
    reportId: string,
    draft: InboxReportActionDraft<ResolveReasonOptionValue> | undefined,
  ) => void;
}

function withoutReport<T>(
  drafts: Record<string, T | undefined>,
  reportId: string,
): Record<string, T | undefined> {
  const next = { ...drafts };
  delete next[reportId];
  return next;
}

export const useInboxReportActionDraftStore =
  create<InboxReportActionDraftState>((set) => ({
    generation: 0,
    dismiss: {},
    resolve: {},
    setDismiss: (generation, reportId, draft) =>
      set((state) =>
        state.generation === generation
          ? {
              dismiss:
                draft === undefined
                  ? withoutReport(state.dismiss, reportId)
                  : { ...state.dismiss, [reportId]: draft },
            }
          : state,
      ),
    setResolve: (generation, reportId, draft) =>
      set((state) =>
        state.generation === generation
          ? {
              resolve:
                draft === undefined
                  ? withoutReport(state.resolve, reportId)
                  : { ...state.resolve, [reportId]: draft },
            }
          : state,
      ),
  }));

export function resetInboxReportActionDrafts(): void {
  useInboxReportActionDraftStore.setState((state) => ({
    generation: state.generation + 1,
    dismiss: {},
    resolve: {},
  }));
}
