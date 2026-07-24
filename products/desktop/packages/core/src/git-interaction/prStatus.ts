import type { PrActionType } from "@posthog/shared";

export type PrVisualIcon = "merged" | "pull-request";

export interface PrAction {
  id: PrActionType;
  label: string;
}

export interface PrVisualConfig {
  color: "gray" | "green" | "red" | "purple";
  icon: PrVisualIcon;
  label: string;
  actions: PrAction[];
}

export function getPrVisualConfig(
  state: string,
  merged: boolean,
  draft: boolean,
): PrVisualConfig {
  if (merged) {
    return {
      color: "purple",
      icon: "merged",
      label: "Merged",
      actions: [],
    };
  }
  if (state === "closed") {
    return {
      color: "red",
      icon: "pull-request",
      label: "Closed",
      actions: [{ id: "reopen", label: "Reopen PR" }],
    };
  }
  if (draft) {
    return {
      color: "gray",
      icon: "pull-request",
      label: "Draft",
      actions: [
        { id: "ready", label: "Ready for review" },
        { id: "close", label: "Close PR" },
      ],
    };
  }
  return {
    color: "green",
    icon: "pull-request",
    label: "Open",
    actions: [
      { id: "draft", label: "Convert to draft" },
      { id: "close", label: "Close PR" },
    ],
  };
}

export function getOptimisticPrState(action: PrActionType) {
  switch (action) {
    case "close":
      return { state: "closed", merged: false, draft: false };
    case "reopen":
      return { state: "open", merged: false, draft: false };
    case "ready":
      return { state: "open", merged: false, draft: false };
    case "draft":
      return { state: "open", merged: false, draft: true };
  }
}

export const PR_ACTION_LABELS: Record<PrActionType, string> = {
  close: "PR closed",
  reopen: "PR reopened",
  ready: "PR marked as ready for review",
  draft: "PR converted to draft",
};

export function parsePrNumber(prUrl: string): string | undefined {
  return prUrl.match(/\/pull\/(\d+)/)?.[1];
}
