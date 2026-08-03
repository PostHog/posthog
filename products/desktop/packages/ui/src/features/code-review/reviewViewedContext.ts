import { createContext, useContext } from "react";

export interface ReviewViewedContextValue {
  viewedRecord: Record<string, string>;
  currentSignatures: Map<string, string>;
  toggleViewed: (key: string, sig: string | null) => void;
}

export const ReviewViewedContext =
  createContext<ReviewViewedContextValue | null>(null);

export function useReviewViewedContext(): ReviewViewedContextValue | null {
  return useContext(ReviewViewedContext);
}
