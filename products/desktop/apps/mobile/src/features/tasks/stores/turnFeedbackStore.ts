import type { AgentTurnFeedbackSentiment } from "@posthog/shared";
import { create } from "zustand";

interface TurnFeedbackState {
  // Keeps the chosen thumb lit as the FlatList recycles turn rows. Feedback is
  // analytics-only, so this is in-memory only and never persisted.
  sentimentByTurnId: Record<string, AgentTurnFeedbackSentiment>;
  setTurnFeedback: (
    turnId: string,
    sentiment: AgentTurnFeedbackSentiment,
  ) => void;
}

export const useTurnFeedbackStore = create<TurnFeedbackState>((set) => ({
  sentimentByTurnId: {},
  setTurnFeedback: (turnId, sentiment) =>
    set((state) => ({
      sentimentByTurnId: { ...state.sentimentByTurnId, [turnId]: sentiment },
    })),
}));

export const useTurnFeedback = (
  turnId: string,
): AgentTurnFeedbackSentiment | null =>
  useTurnFeedbackStore((s) => s.sentimentByTurnId[turnId] ?? null);
