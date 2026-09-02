import type { Theme } from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import {
  renderWebFetchCall,
  renderWebFetchResult,
  renderWebResult,
  renderWebSearchCall,
  renderWebSearchResult,
} from "./render";

/** Identity theme — no ANSI styling, so rendered text matches plain content. */
const fakeTheme = {
  fg: (_name: string, text: string) => text,
  bold: (text: string) => text,
} as unknown as Theme;

function renderText(component: {
  render: (width: number) => string[];
}): string {
  // Text pads every line out to the full render width; trim that padding
  // so assertions can compare against plain expected content.
  return component
    .render(1000)
    .map((line) => line.trimEnd())
    .join("\n");
}

function result(content: Array<{ type: string; text?: string }>) {
  return { content };
}

describe("renderWebSearchCall", () => {
  it("renders the query", () => {
    expect(
      renderText(
        renderWebSearchCall({ query: "posthog release notes" }, fakeTheme),
      ),
    ).toBe("web_search posthog release notes");
  });

  it("renders a placeholder when args are missing", () => {
    expect(renderText(renderWebSearchCall({}, fakeTheme))).toBe(
      "web_search ...",
    );
  });

  it("appends the context size when provided", () => {
    expect(
      renderText(
        renderWebSearchCall(
          { query: "x", search_context_size: "high" },
          fakeTheme,
        ),
      ),
    ).toBe("web_search x (high)");
  });
});

describe("renderWebFetchCall", () => {
  it("renders the url", () => {
    expect(
      renderText(
        renderWebFetchCall({ url: "https://example.com/page" }, fakeTheme),
      ),
    ).toBe("web_fetch https://example.com/page");
  });

  it("renders a placeholder when args are missing", () => {
    expect(renderText(renderWebFetchCall({}, fakeTheme))).toBe("web_fetch ...");
  });

  it("appends the prompt on a second line", () => {
    const text = renderText(
      renderWebFetchCall(
        { url: "https://example.com", prompt: "extract the title" },
        fakeTheme,
      ),
    );
    expect(text.split("\n")).toEqual([
      "web_fetch https://example.com",
      "  extract the title",
    ]);
  });
});

describe("renderWebResult (shared)", () => {
  describe("partial results", () => {
    it.each([
      ["web_search", "Searching...", renderWebSearchResult],
      ["web_fetch", "Fetching...", renderWebFetchResult],
    ] as const)(
      "shows the %s partial label while streaming",
      (_label, expected, fn) => {
        expect(
          renderText(
            fn(
              result([{ type: "text", text: "ignored" }]),
              { expanded: false, isPartial: true },
              fakeTheme,
              false,
            ),
          ),
        ).toBe(expected);
      },
    );

    it("shows the error body rather than the partial label when an error arrives mid-stream", () => {
      // isPartial + error: the error is surfaced, not hidden behind the
      // streaming label.
      expect(
        renderText(
          renderWebSearchResult(
            result([{ type: "text", text: "err" }]),
            { expanded: false, isPartial: true },
            fakeTheme,
            true,
          ),
        ),
      ).toBe("\nerr");
    });
  });

  describe("empty output", () => {
    it("shows a placeholder when there is no text content", () => {
      expect(
        renderText(
          renderWebSearchResult(
            result([{ type: "image", text: "x" }]),
            { expanded: false, isPartial: false },
            fakeTheme,
            false,
          ),
        ),
      ).toBe("No output");
    });
  });

  describe("collapsed (default)", () => {
    it("shows the full body when under the preview limit", () => {
      const body = "line one\nline two";
      const text = renderText(
        renderWebResult(
          result([{ type: "text", text: body }]),
          { expanded: false, isPartial: false },
          fakeTheme,
          false,
          "Searching...",
        ),
      );
      // A leading blank line separates the result body from the call header.
      expect(text).toBe("\nline one\nline two");
    });

    it("truncates beyond the 15-line preview with an expand hint", () => {
      const body = Array.from({ length: 30 }, (_, i) => `line ${i}`).join("\n");
      const text = renderText(
        renderWebResult(
          result([{ type: "text", text: body }]),
          { expanded: false, isPartial: false },
          fakeTheme,
          false,
          "Searching...",
        ),
      );
      const lines = text.split("\n");
      // leading blank separator + 15 preview lines + 1 expand-hint footer line
      expect(lines).toHaveLength(17);
      expect(lines[1]).toBe("line 0");
      expect(lines[15]).toBe("line 14");
      expect(lines.at(-1)).toContain("15 more lines");
      expect(lines.at(-1)).toContain("expand");
    });

    it("does not show an expand hint when exactly at the preview limit", () => {
      const body = Array.from({ length: 15 }, (_, i) => `line ${i}`).join("\n");
      const text = renderText(
        renderWebResult(
          result([{ type: "text", text: body }]),
          { expanded: false, isPartial: false },
          fakeTheme,
          false,
          "Searching...",
        ),
      );
      // leading blank separator + 15 lines, no footer
      expect(text.split("\n")).toHaveLength(16);
      expect(text).not.toContain("more lines");
    });
  });

  describe("expanded", () => {
    it("shows the full body with no truncation footer", () => {
      const body = Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\n");
      const text = renderText(
        renderWebResult(
          result([{ type: "text", text: body }]),
          { expanded: true, isPartial: false },
          fakeTheme,
          false,
          "Searching...",
        ),
      );
      const lines = text.split("\n");
      // leading blank separator + 40 lines
      expect(lines).toHaveLength(41);
      expect(lines.at(-1)).toBe("line 39");
      expect(text).not.toContain("more lines");
    });
  });

  describe("errors", () => {
    it("shows the full error body even when collapsed", () => {
      const body = Array.from({ length: 30 }, (_, i) => `err ${i}`).join("\n");
      const text = renderText(
        renderWebResult(
          result([{ type: "text", text: body }]),
          { expanded: false, isPartial: false },
          fakeTheme,
          true,
          "Searching...",
        ),
      );
      const lines = text.split("\n");
      // leading blank separator + 30 error lines
      expect(lines).toHaveLength(31);
      expect(lines.at(-1)).toBe("err 29");
      expect(text).not.toContain("more lines");
    });
  });
});
