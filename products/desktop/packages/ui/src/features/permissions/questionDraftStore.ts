import type { StepAnswer } from "@posthog/ui/primitives/ActionSelector";
import { create } from "zustand";

export interface QuestionDraft {
  activeStep: number;
  stepAnswers: Map<number, StepAnswer>;
}

interface QuestionDraftState {
  drafts: Map<string, QuestionDraft>;
  setActiveStep: (toolCallId: string, activeStep: number) => void;
  setStepAnswer: (
    toolCallId: string,
    stepIndex: number,
    answer: StepAnswer,
  ) => void;
  clearDraft: (toolCallId: string) => void;
}

/** Bounds memory for drafts of cards that resolved without a submit/cancel. */
const MAX_DRAFTS = 50;

function upsertDraft(
  drafts: Map<string, QuestionDraft>,
  toolCallId: string,
  update: (existing: QuestionDraft) => QuestionDraft,
): Map<string, QuestionDraft> {
  const next = new Map(drafts);
  const existing = next.get(toolCallId) ?? {
    activeStep: 0,
    stepAnswers: new Map<number, StepAnswer>(),
  };
  // Re-insert so insertion order tracks recency and eviction drops the stalest.
  next.delete(toolCallId);
  next.set(toolCallId, update(existing));
  while (next.size > MAX_DRAFTS) {
    const oldest = next.keys().next().value;
    if (oldest === undefined) break;
    next.delete(oldest);
  }
  return next;
}

/**
 * In-progress AskUserQuestion answers, keyed by toolCallId. The question card
 * unmounts whenever the user switches chats; holding the step answers here
 * instead of component state lets a remounted card restore them rather than
 * resetting to the first question.
 */
export const useQuestionDraftStore = create<QuestionDraftState>((set) => ({
  drafts: new Map(),
  setActiveStep: (toolCallId, activeStep) =>
    set((state) => ({
      drafts: upsertDraft(state.drafts, toolCallId, (draft) => ({
        ...draft,
        activeStep,
      })),
    })),
  setStepAnswer: (toolCallId, stepIndex, answer) =>
    set((state) => ({
      drafts: upsertDraft(state.drafts, toolCallId, (draft) => ({
        ...draft,
        stepAnswers: new Map(draft.stepAnswers).set(stepIndex, answer),
      })),
    })),
  clearDraft: (toolCallId) =>
    set((state) => {
      if (!state.drafts.has(toolCallId)) return state;
      const drafts = new Map(state.drafts);
      drafts.delete(toolCallId);
      return { drafts };
    }),
}));
