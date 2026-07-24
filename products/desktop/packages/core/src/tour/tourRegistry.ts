import type { TourDefinition } from "@posthog/core/tour/types";

const TOUR_REGISTRY: Record<string, TourDefinition> = {};

export function registerTour(tour: TourDefinition): void {
  TOUR_REGISTRY[tour.id] = tour;
}

export function getTour(tourId: string): TourDefinition | null {
  return TOUR_REGISTRY[tourId] ?? null;
}

export function getRegisteredTours(): TourDefinition[] {
  return Object.values(TOUR_REGISTRY);
}
