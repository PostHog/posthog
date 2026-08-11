import type { PrConversationComment } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { combinePrCommentResults } from "./usePrCommentsForUrls";

describe("combinePrCommentResults", () => {
  it("keeps successful PR comments when another PR fails", () => {
    const comment = { id: 1, body: "Looks good" } as PrConversationComment;
    const result = combinePrCommentResults(
      ["pr-1", "pr-2"],
      [
        { data: null, isLoading: false, isError: true },
        { data: [comment], isLoading: false, isError: false },
      ],
    );

    expect(result.byUrl).toEqual([
      ["pr-1", []],
      ["pr-2", [comment]],
    ]);
    expect(result.isError).toBe(false);
  });
});
