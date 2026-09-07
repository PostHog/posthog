import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWebSearchTool,
  formatSearchResult,
  parseSearchContextSize,
} from "./web-search";

describe("parseSearchContextSize", () => {
  it.each([
    ["low", "low"],
    ["medium", "medium"],
    ["high", "high"],
    [undefined, "medium"],
    ["xlarge", "medium"],
    ["", "medium"],
  ])("parseSearchContextSize(%j) → %s", (input, expected) => {
    expect(parseSearchContextSize(input as string | undefined)).toBe(expected);
  });
});

describe("formatSearchResult", () => {
  it.each([
    ["empty annotations", "Hello world", [], "Hello world", 0],
    ["undefined annotations", "Hello world", undefined, "Hello world", 0],
  ])(
    "%s → no sources block",
    (_label, text, annotations, expectedText, expectedCitations) => {
      const result = formatSearchResult(
        text as string,
        annotations as
          | Array<{ type: string; url: string; title: string }>
          | undefined,
      );
      expect(result.formatted).toBe(expectedText);
      expect(result.citations).toHaveLength(expectedCitations as number);
    },
  );

  it("appends deduplicated source links", () => {
    const result = formatSearchResult("Answer text", [
      { type: "url_citation", url: "https://a.com", title: "Source A" },
      { type: "url_citation", url: "https://b.com", title: "Source B" },
    ]);
    expect(result.formatted).toContain("Sources:");
    expect(result.formatted).toContain("- [Source A](https://a.com)");
    expect(result.formatted).toContain("- [Source B](https://b.com)");
    expect(result.citations).toHaveLength(2);
  });

  it("deduplicates citations with the same URL", () => {
    const result = formatSearchResult("Text", [
      { type: "url_citation", url: "https://a.com", title: "First" },
      { type: "url_citation", url: "https://a.com", title: "Duplicate" },
      { type: "url_citation", url: "https://b.com", title: "Second" },
    ]);
    expect(result.formatted).toContain("- [First](https://a.com)");
    expect(result.formatted).not.toContain("Duplicate");
    expect(result.formatted).toContain("- [Second](https://b.com)");
  });

  it("filters out non-url_citation annotations", () => {
    const result = formatSearchResult("Text", [
      { type: "url_citation", url: "https://a.com", title: "Real" },
      { type: "other_type", url: "https://b.com", title: "Not a citation" },
    ]);
    expect(result.citations).toHaveLength(1);
    expect(result.formatted).not.toContain("Not a citation");
  });

  it("preserves all citations in array while deduping in formatted output", () => {
    const result = formatSearchResult("Text", [
      { type: "url_citation", url: "https://a.com", title: "First" },
      { type: "url_citation", url: "https://a.com", title: "Second mention" },
    ]);
    expect(result.citations).toHaveLength(2);
    const sourceLines =
      result.formatted
        .split("Sources:\n")[1]
        ?.split("\n")
        .filter((l) => l.startsWith("- ")) ?? [];
    expect(sourceLines).toHaveLength(1);
  });
});

function fakeCtx(apiKey: string | undefined): ExtensionContext {
  return {
    modelRegistry: {
      getApiKeyForProvider: vi.fn().mockResolvedValue(apiKey),
    },
  } as unknown as ExtensionContext;
}

describe("createWebSearchTool", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("throws when no gateway credentials are available", async () => {
    const tool = createWebSearchTool({ region: "us" });
    await expect(
      tool.execute(
        "call-1",
        { query: "hello" },
        undefined,
        undefined,
        fakeCtx(undefined),
      ),
    ).rejects.toThrow(/No PostHog gateway credentials/);
  });

  it("calls the gateway responses API and formats the result", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        output: [
          {
            type: "message",
            content: [
              {
                type: "output_text",
                text: "The answer",
                annotations: [
                  { type: "url_citation", url: "https://a.com", title: "A" },
                ],
              },
            ],
          },
        ],
        usage: { input_tokens: 1, output_tokens: 2, total_tokens: 3 },
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const tool = createWebSearchTool({ region: "us", apiKey: "pha_test" });
    const result = await tool.execute(
      "call-1",
      { query: "what happened today" },
      undefined,
      undefined,
      fakeCtx(undefined),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "https://gateway.us.posthog.com/posthog_code/v1/responses",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer pha_test" }),
      }),
    );
    expect(result.content[0]).toMatchObject({
      type: "text",
      text: expect.stringContaining("The answer"),
    });
    expect(result.details).toMatchObject({
      citations: [{ type: "url_citation", url: "https://a.com", title: "A" }],
    });
  });

  it("throws a descriptive error on a non-ok response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "boom",
    }) as unknown as typeof fetch;

    const tool = createWebSearchTool({ region: "us", apiKey: "pha_test" });
    await expect(
      tool.execute(
        "call-1",
        { query: "x" },
        undefined,
        undefined,
        fakeCtx(undefined),
      ),
    ).rejects.toThrow(/Web search failed \(500\)/);
  });
});

describe("createWebSearchTool with dynamic auth", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ output: [] }),
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("falls back to the posthog provider's resolved api key", async () => {
    const tool = createWebSearchTool({ region: "eu" });
    await tool.execute(
      "call-1",
      { query: "x" },
      undefined,
      undefined,
      fakeCtx("pha_from_registry"),
    );

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "https://gateway.eu.posthog.com/posthog_code/v1/responses",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer pha_from_registry",
        }),
      }),
    );
  });
});
