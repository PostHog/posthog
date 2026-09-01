import { create } from "zustand";

export type IpcOpType = "query" | "mutation" | "subscription";

export interface IpcTimingEntry {
  id: number;
  path: string;
  type: IpcOpType;
  rttMs: number;
  inputBytes: number;
  outputBytes: number;
  ok: boolean;
  startedAt: number;
}

const RING_BUFFER_SIZE = 1000;

interface IpcMetricsState {
  entries: IpcTimingEntry[];
  inFlight: number;
  peakInFlight: number;
  recordStart: () => void;
  recordEnd: (entry: Omit<IpcTimingEntry, "id">) => void;
  clear: () => void;
}

let nextId = 1;

export const useIpcMetricsStore = create<IpcMetricsState>()((set) => ({
  entries: [],
  inFlight: 0,
  peakInFlight: 0,

  recordStart: () =>
    set((state) => {
      const inFlight = state.inFlight + 1;
      return {
        inFlight,
        peakInFlight: Math.max(state.peakInFlight, inFlight),
      };
    }),

  recordEnd: (entry) =>
    set((state) => {
      const next = [...state.entries, { id: nextId++, ...entry }];
      const trimmed =
        next.length > RING_BUFFER_SIZE
          ? next.slice(next.length - RING_BUFFER_SIZE)
          : next;
      return {
        entries: trimmed,
        inFlight: Math.max(0, state.inFlight - 1),
      };
    }),

  clear: () =>
    set({
      entries: [],
      peakInFlight: 0,
    }),
}));
