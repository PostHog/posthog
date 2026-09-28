import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useCommentState, useCommentText } from "./useCommentState";

describe("review comment state", () => {
  it("keeps an unfinished comment across a file diff remount", () => {
    const taskId = crypto.randomUUID();
    const filePath = "src/example.ts";
    const comment = renderHook(() => useCommentState(taskId, filePath));
    const text = renderHook(() => useCommentText(taskId, filePath));

    act(() => {
      comment.result.current.handleLineSelectionEnd({
        start: 4,
        end: 4,
        side: "additions",
        endSide: "additions",
      });
      text.result.current.setText("Please check this case");
    });
    comment.unmount();
    text.unmount();

    const restoredComment = renderHook(() => useCommentState(taskId, filePath));
    const restoredText = renderHook(() => useCommentText(taskId, filePath));
    expect(restoredComment.result.current.commentAnnotation?.lineNumber).toBe(
      4,
    );
    expect(restoredText.result.current.text).toBe("Please check this case");

    act(() => restoredComment.result.current.reset());
    expect(restoredComment.result.current.commentAnnotation).toBeNull();
    expect(restoredText.result.current.text).toBeUndefined();
  });
});
