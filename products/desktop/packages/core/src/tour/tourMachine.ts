import type { TourDefinition } from "@posthog/core/tour/types";

export interface TourState {
  completedTourIds: string[];
  activeTourId: string | null;
  activeStepIndex: number;
}

export type TourAction =
  | "started"
  | "step_advanced"
  | "completed"
  | "dismissed";

export interface TourEvent {
  tour_id: string;
  action: TourAction;
  step_id?: string;
  step_index?: number;
  total_steps?: number;
}

export interface TourTransition {
  state: TourState;
  events: TourEvent[];
}

export type GetTour = (tourId: string) => TourDefinition | null;

export function startTour(
  state: TourState,
  tourId: string,
  getTour: GetTour,
): TourTransition {
  if (
    state.completedTourIds.includes(tourId) ||
    state.activeTourId === tourId
  ) {
    return { state, events: [] };
  }

  const tour = getTour(tourId);
  return {
    state: { ...state, activeTourId: tourId, activeStepIndex: 0 },
    events: [
      {
        tour_id: tourId,
        action: "started",
        step_id: tour?.steps[0]?.id,
        step_index: 0,
        total_steps: tour?.steps.length,
      },
    ],
  };
}

export function advance(
  state: TourState,
  tourId: string,
  stepId: string,
  getTour: GetTour,
): TourTransition {
  if (state.activeTourId !== tourId) return { state, events: [] };

  const tour = getTour(state.activeTourId);
  if (!tour) return { state, events: [] };

  const currentStep = tour.steps[state.activeStepIndex];
  if (!currentStep || currentStep.id !== stepId) return { state, events: [] };

  const events: TourEvent[] = [
    {
      tour_id: tourId,
      action: "step_advanced",
      step_id: stepId,
      step_index: state.activeStepIndex,
      total_steps: tour.steps.length,
    },
  ];

  if (state.activeStepIndex >= tour.steps.length - 1) {
    events.push({
      tour_id: tourId,
      action: "completed",
      total_steps: tour.steps.length,
    });
    return {
      state: {
        ...state,
        completedTourIds: [...state.completedTourIds, tourId],
        activeTourId: null,
        activeStepIndex: 0,
      },
      events,
    };
  }

  return {
    state: { ...state, activeStepIndex: state.activeStepIndex + 1 },
    events,
  };
}

export function completeTour(
  state: TourState,
  tourId: string,
  getTour: GetTour,
): TourTransition {
  if (state.completedTourIds.includes(tourId)) return { state, events: [] };

  const tour = getTour(tourId);
  return {
    state: {
      ...state,
      completedTourIds: [...state.completedTourIds, tourId],
      activeTourId: null,
      activeStepIndex: 0,
    },
    events: [
      {
        tour_id: tourId,
        action: "completed",
        total_steps: tour?.steps.length,
      },
    ],
  };
}

export function dismiss(state: TourState, getTour: GetTour): TourTransition {
  if (!state.activeTourId) return { state, events: [] };

  const tour = getTour(state.activeTourId);
  return {
    state: {
      ...state,
      completedTourIds: [...state.completedTourIds, state.activeTourId],
      activeTourId: null,
      activeStepIndex: 0,
    },
    events: [
      {
        tour_id: state.activeTourId,
        action: "dismissed",
        step_id: tour?.steps[state.activeStepIndex]?.id,
        step_index: state.activeStepIndex,
        total_steps: tour?.steps.length,
      },
    ],
  };
}

export function computeReturningUserMigration(
  tours: TourDefinition[],
  hasCompletedOnboarding: boolean,
): string[] {
  if (!hasCompletedOnboarding) return [];
  return tours
    .filter((tour) => tour.completeForReturningUsers)
    .map((tour) => tour.id);
}
