import { describe, expect, it } from "vitest";
import {
  getDefaultReviewMode,
  REVIEW_SPLIT_MIN_WINDOW_WIDTH,
} from "./getDefaultReviewMode";

describe("getDefaultReviewMode", () => {
  it.each([
    [REVIEW_SPLIT_MIN_WINDOW_WIDTH - 1, "expanded"],
    [REVIEW_SPLIT_MIN_WINDOW_WIDTH, "split"],
    [REVIEW_SPLIT_MIN_WINDOW_WIDTH + 1, "split"],
  ] as const)("returns the review mode for a %ipx window", (width, mode) => {
    expect(getDefaultReviewMode(width)).toBe(mode);
  });
});
