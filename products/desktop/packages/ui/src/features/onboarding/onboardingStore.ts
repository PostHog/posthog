import type { OnboardingStep } from "@posthog/ui/features/onboarding/types";
import { logger } from "@posthog/ui/shell/logger";
import { create } from "zustand";
import { persist } from "zustand/middleware";

const log = logger.scope("onboarding-store");

interface OnboardingStoreState {
  currentStep: OnboardingStep;
  hasCompletedOnboarding: boolean;
  hasShippedFirstPr: boolean;
  selectedProjectId: number | null;
}

interface OnboardingStoreActions {
  setCurrentStep: (step: OnboardingStep) => void;
  completeOnboarding: () => void;
  markFirstPrShipped: () => void;
  resetOnboarding: () => void;
  resetSelections: () => void;
  selectProjectId: (projectId: number | null) => void;
}

type OnboardingStore = OnboardingStoreState & OnboardingStoreActions;

const initialState: OnboardingStoreState = {
  currentStep: "project-select",
  hasCompletedOnboarding: false,
  hasShippedFirstPr: false,
  selectedProjectId: null,
};

export function migrateOnboardingState(
  persistedState: unknown,
): OnboardingStore {
  const state = persistedState as OnboardingStore;
  if ((state.currentStep as string) === "invite-code") {
    return { ...state, currentStep: "consent" };
  }
  return state;
}

export const useOnboardingStore = create<OnboardingStore>()(
  persist(
    (set) => ({
      ...initialState,

      setCurrentStep: (step) => set({ currentStep: step }),
      completeOnboarding: () => {
        log.info("completeOnboarding");
        set({ hasCompletedOnboarding: true });
      },
      markFirstPrShipped: () => set({ hasShippedFirstPr: true }),
      resetOnboarding: () => set({ ...initialState }),
      resetSelections: () =>
        set({
          currentStep: "project-select",
          selectedProjectId: null,
        }),
      selectProjectId: (selectedProjectId) => set({ selectedProjectId }),
    }),
    {
      name: "onboarding-store",
      version: 1,
      migrate: migrateOnboardingState,
      partialize: (state) => ({
        currentStep: state.currentStep,
        hasCompletedOnboarding: state.hasCompletedOnboarding,
        hasShippedFirstPr: state.hasShippedFirstPr,
        selectedProjectId: state.selectedProjectId,
      }),
    },
  ),
);
