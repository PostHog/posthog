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
  dismiss: Record<
    string,
    InboxReportActionDraft<DismissalReasonOptionValue> | undefined
  >;
  resolve: Record<
    string,
    InboxReportActionDraft<ResolveReasonOptionValue> | undefined
  >;
  setDismiss: (
    reportId: string,
    draft: InboxReportActionDraft<DismissalReasonOptionValue> | undefined,
  ) => void;
  setResolve: (
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
    dismiss: {},
    resolve: {},
    setDismiss: (reportId, draft) =>
      set((state) => ({
        dismiss:
          draft === undefined
            ? withoutReport(state.dismiss, reportId)
            : { ...state.dismiss, [reportId]: draft },
      })),
    setResolve: (reportId, draft) =>
      set((state) => ({
        resolve:
          draft === undefined
            ? withoutReport(state.resolve, reportId)
            : { ...state.resolve, [reportId]: draft },
      })),
  }));

export function resetInboxReportActionDrafts(): void {
  useInboxReportActionDraftStore.setState({ dismiss: {}, resolve: {} });
}
