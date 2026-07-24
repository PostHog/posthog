export type TourStepAdvance = { type: "action" } | { type: "click" };

export type TooltipPlacement = "right" | "left" | "top" | "bottom";

export interface TourStep {
  id: string;
  target: string;
  hogSrc: string;
  message: string;
  advanceOn: TourStepAdvance;
  preferredPlacement?: TooltipPlacement;
}

export interface TourDefinition {
  id: string;
  steps: TourStep[];
  completeForReturningUsers?: boolean;
}
