import { describe, expect, it } from "vitest";
import {
  createTextCommentAnchor,
  isThreadResolved,
  parseCommentContext,
  resolveTextCommentAnchor,
} from "./anchors";

describe("artifact text anchors", () => {
  it("creates and resolves a verified positional anchor", () => {
    const text = "Before selected words after";
    const anchor = createTextCommentAnchor(text, 7, 21);

    if (!anchor) throw new Error("Expected an anchor");
    expect(resolveTextCommentAnchor(text, anchor)).toEqual({
      start: 7,
      end: 21,
      status: "exact",
    });
  });

  it("reanchors a quote after surrounding content changes", () => {
    const original = "Before selected words after";
    const anchor = createTextCommentAnchor(original, 7, 21);
    if (!anchor) throw new Error("Expected an anchor");
    const changed = `New introduction. ${original}`;

    expect(resolveTextCommentAnchor(changed, anchor)).toEqual({
      start: 25,
      end: 39,
      status: "reanchored",
    });
  });

  it("uses context to disambiguate repeated quotes", () => {
    const original = "first repeated phrase then second repeated phrase end";
    const start = original.lastIndexOf("repeated phrase");
    const anchor = createTextCommentAnchor(
      original,
      start,
      start + "repeated phrase".length,
    );
    if (!anchor) throw new Error("Expected an anchor");
    const changed = `prefix ${original}`;

    expect(resolveTextCommentAnchor(changed, anchor)?.start).toBe(
      changed.lastIndexOf("repeated phrase"),
    );
  });

  it("orphans deleted and ambiguous text instead of guessing", () => {
    const deleted = createTextCommentAnchor("unique text", 0, 6);
    if (!deleted) throw new Error("Expected an anchor");
    expect(resolveTextCommentAnchor("replacement", deleted)).toBeNull();

    const ambiguous = {
      kind: "text" as const,
      quote: "same",
      prefix: "",
      suffix: "",
      start: 100,
      end: 104,
    };
    expect(resolveTextCommentAnchor("same x same", ambiguous)).toBeNull();
  });

  it("rejects whitespace-only selections", () => {
    expect(createTextCommentAnchor("a   b", 1, 4)).toBeNull();
  });

  it("rejects selections larger than the persisted anchor contract", () => {
    const text = "x".repeat(10_001);
    expect(createTextCommentAnchor(text, 0, text.length)).toBeNull();
  });

  it("validates versioned comment context and anchor bounds", () => {
    expect(
      parseCommentContext({
        anchor: { kind: "document" },
        canvasVersionId: "version-2",
      }),
    ).toEqual({
      anchor: { kind: "document" },
      canvasVersionId: "version-2",
    });
    expect(
      parseCommentContext({
        anchor: {
          kind: "text",
          quote: "x".repeat(10_001),
          prefix: "",
          suffix: "",
          start: 0,
          end: 10_001,
        },
      }),
    ).toBeNull();
  });

  it("uses the latest thread-state event for resolution", () => {
    const root = { completed_at: null };
    const event = (state: "resolved" | "open", created_at: string) => ({
      created_at,
      item_context: {
        anchor: { kind: "document" as const },
        threadState: state,
      },
    });

    expect(
      isThreadResolved(root, [
        event("resolved", "2026-01-01T00:00:00Z"),
        event("open", "2026-01-01T00:01:00Z"),
      ]),
    ).toBe(false);
    expect(
      isThreadResolved(root, [
        event("open", "2026-01-01T00:00:00Z"),
        event("resolved", "2026-01-01T00:01:00Z"),
      ]),
    ).toBe(true);
  });
});
