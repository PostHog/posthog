import {
  advance,
  completeTour,
  computeReturningUserMigration,
  dismiss,
  type GetTour,
  startTour,
  type TourState,
} from "@posthog/core/tour/tourMachine";
import type { TourDefinition } from "@posthog/core/tour/types";
import { describe, expect, it } from "vitest";

const tour: TourDefinition = {
  id: "demo",
  steps: [
    {
      id: "s1",
      target: "t1",
      hogSrc: "",
      message: "",
      advanceOn: { type: "click" },
    },
    {
      id: "s2",
      target: "t2",
      hogSrc: "",
      message: "",
      advanceOn: { type: "click" },
    },
  ],
};

const getTour: GetTour = (id) => (id === "demo" ? tour : null);

const initial: TourState = {
  completedTourIds: [],
  activeTourId: null,
  activeStepIndex: 0,
};

describe("startTour", () => {
  it("activates the tour at step 0 and emits started", () => {
    const { state, events } = startTour(initial, "demo", getTour);
    expect(state.activeTourId).toBe("demo");
    expect(state.activeStepIndex).toBe(0);
    expect(events[0]).toMatchObject({
      tour_id: "demo",
      action: "started",
      step_id: "s1",
      total_steps: 2,
    });
  });

  it("is a no-op when the tour is already completed", () => {
    const state = { ...initial, completedTourIds: ["demo"] };
    const result = startTour(state, "demo", getTour);
    expect(result.state).toBe(state);
    expect(result.events).toHaveLength(0);
  });

  it("is a no-op when the tour is already active", () => {
    const state = { ...initial, activeTourId: "demo" };
    const result = startTour(state, "demo", getTour);
    expect(result.events).toHaveLength(0);
  });
});

describe("advance", () => {
  it("moves to the next step when not at the last step", () => {
    const state = { ...initial, activeTourId: "demo", activeStepIndex: 0 };
    const { state: next, events } = advance(state, "demo", "s1", getTour);
    expect(next.activeStepIndex).toBe(1);
    expect(next.activeTourId).toBe("demo");
    expect(events).toHaveLength(1);
    expect(events[0].action).toBe("step_advanced");
  });

  it("completes the tour when advancing the last step", () => {
    const state = { ...initial, activeTourId: "demo", activeStepIndex: 1 };
    const { state: next, events } = advance(state, "demo", "s2", getTour);
    expect(next.activeTourId).toBeNull();
    expect(next.completedTourIds).toContain("demo");
    expect(events.map((e) => e.action)).toEqual(["step_advanced", "completed"]);
  });

  it("is a no-op when the active tour does not match", () => {
    const state = { ...initial, activeTourId: "other", activeStepIndex: 0 };
    const result = advance(state, "demo", "s1", getTour);
    expect(result.events).toHaveLength(0);
  });

  it("is a no-op when the step id does not match the current step", () => {
    const state = { ...initial, activeTourId: "demo", activeStepIndex: 0 };
    const result = advance(state, "demo", "s2", getTour);
    expect(result.events).toHaveLength(0);
    expect(result.state.activeStepIndex).toBe(0);
  });
});

describe("completeTour", () => {
  it("marks the tour complete and clears active state", () => {
    const state = { ...initial, activeTourId: "demo", activeStepIndex: 1 };
    const { state: next, events } = completeTour(state, "demo", getTour);
    expect(next.completedTourIds).toContain("demo");
    expect(next.activeTourId).toBeNull();
    expect(events[0].action).toBe("completed");
  });

  it("is a no-op when already complete", () => {
    const state = { ...initial, completedTourIds: ["demo"] };
    const result = completeTour(state, "demo", getTour);
    expect(result.events).toHaveLength(0);
  });
});

describe("dismiss", () => {
  it("treats dismissal as completion of the active tour", () => {
    const state = { ...initial, activeTourId: "demo", activeStepIndex: 1 };
    const { state: next, events } = dismiss(state, getTour);
    expect(next.completedTourIds).toContain("demo");
    expect(next.activeTourId).toBeNull();
    expect(events[0].action).toBe("dismissed");
    expect(events[0].step_index).toBe(1);
  });

  it("is a no-op when no tour is active", () => {
    const result = dismiss(initial, getTour);
    expect(result.events).toHaveLength(0);
  });
});

describe("computeReturningUserMigration", () => {
  const tours: TourDefinition[] = [
    { id: "a", steps: [], completeForReturningUsers: true },
    { id: "b", steps: [], completeForReturningUsers: false },
    { id: "c", steps: [] },
  ];

  it("returns ids flagged for returning users when onboarding is complete", () => {
    expect(computeReturningUserMigration(tours, true)).toEqual(["a"]);
  });

  it("returns nothing when onboarding is incomplete", () => {
    expect(computeReturningUserMigration(tours, false)).toEqual([]);
  });
});
