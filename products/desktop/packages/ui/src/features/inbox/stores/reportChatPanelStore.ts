import { create } from "zustand";

interface ReportChatPanelState {
  /** Whether the chat dock is showing beside the open report. */
  open: boolean;
  width: number;
  /**
   * Task ids of discussions started this session, per report. Bridges the gap
   * between creating the discussion task and its task_run artefact appearing
   * in the report's artefact list (the durable association).
   */
  startedTaskIdByReport: Record<string, string>;
  /**
   * A highlighted passage waiting to be quoted into the report's chat
   * composer. Written by the selection affordance, consumed once by the panel.
   */
  pendingQuoteByReport: Record<string, string>;
  /**
   * The starter question typed before a discussion exists, per report. Held in
   * the store rather than component state so closing the panel — which unmounts
   * the starter — keeps the draft (and any quote folded into it). Cleared once a
   * discussion task is created.
   */
  starterDraftByReport: Record<string, string>;
  setOpen: (open: boolean) => void;
  setWidth: (width: number) => void;
  rememberStartedTask: (reportId: string, taskId: string) => void;
  setPendingQuote: (reportId: string, quote: string) => void;
  takePendingQuote: (reportId: string) => string | null;
  setStarterDraft: (reportId: string, text: string) => void;
  clearStarterDraft: (reportId: string) => void;
}

export const useReportChatPanelStore = create<ReportChatPanelState>(
  (set, get) => ({
    open: false,
    width: 420,
    startedTaskIdByReport: {},
    pendingQuoteByReport: {},
    starterDraftByReport: {},
    setOpen: (open) => set({ open }),
    setWidth: (width) => set({ width }),
    rememberStartedTask: (reportId, taskId) =>
      set((state) => ({
        startedTaskIdByReport: {
          ...state.startedTaskIdByReport,
          [reportId]: taskId,
        },
      })),
    setPendingQuote: (reportId, quote) =>
      set((state) => ({
        pendingQuoteByReport: {
          ...state.pendingQuoteByReport,
          [reportId]: quote,
        },
      })),
    takePendingQuote: (reportId) => {
      const quote = get().pendingQuoteByReport[reportId];
      if (!quote) return null;
      set((state) => {
        const { [reportId]: _, ...rest } = state.pendingQuoteByReport;
        return { pendingQuoteByReport: rest };
      });
      return quote;
    },
    setStarterDraft: (reportId, text) =>
      set((state) => ({
        starterDraftByReport: {
          ...state.starterDraftByReport,
          [reportId]: text,
        },
      })),
    clearStarterDraft: (reportId) =>
      set((state) => {
        if (!(reportId in state.starterDraftByReport)) return state;
        const { [reportId]: _, ...rest } = state.starterDraftByReport;
        return { starterDraftByReport: rest };
      }),
  }),
);
