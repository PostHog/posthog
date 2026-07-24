import { registerTour } from "@posthog/core/tour/tourRegistry";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { useTourStore } from "@posthog/ui/features/tour/tourStore";
import { createFirstTaskTour } from "@posthog/ui/features/tour/tours/createFirstTaskTour";

export function initTours(): void {
  registerTour(createFirstTaskTour);
  const { hasCompletedOnboarding } = useOnboardingStore.getState();
  useTourStore.getState().applyReturningUserMigration(hasCompletedOnboarding);
}
