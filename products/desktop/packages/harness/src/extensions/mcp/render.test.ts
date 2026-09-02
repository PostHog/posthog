import type {
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import type { Hit } from "./proxy-tool";
import {
  formatArgsCompact,
  formatArgsExpanded,
  renderMcpProxyCall,
  renderMcpProxyResult,
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

function resultOptions(
  overrides: Partial<ToolRenderResultOptions> = {},
): ToolRenderResultOptions {
  return { expanded: false, isPartial: false, ...overrides };
}

describe("formatArgsCompact", () => {
  it.each([
    ["object args", { id: 42, name: "demo" }, '{"id":42,"name":"demo"}'],
    ["string coerced to JSON", { q: "NaN" }, '{"q":"NaN"}'],
    ["nested args", { filter: { ids: [1, 2] } }, '{"filter":{"ids":[1,2]}}'],
    ["empty object", {}, ""],
    ["undefined", undefined, ""],
    ["null", null, ""],
  ])("formats %s", (_label, args, expected) => {
    expect(formatArgsCompact(args)).toBe(expected);
  });

  it("truncates long args with an ellipsis", () => {
    const result = formatArgsCompact({ text: "x".repeat(300) }, 50);
    expect(result).toHaveLength(50);
    expect(result.endsWith("…")).toBe(true);
  });

  it("falls back to String() for non-serializable args", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(formatArgsCompact(circular)).toBe("[object Object]");
  });
});

describe("formatArgsExpanded", () => {
  it("pretty-prints arguments", () => {
    expect(formatArgsExpanded({ id: 1 })).toBe('{\n  "id": 1\n}');
  });

  it.each([
    ["empty object", {}],
    ["undefined", undefined],
    ["null", null],
  ])("returns empty for %s", (_label, args) => {
    expect(formatArgsExpanded(args)).toBe("");
  });
});

describe("renderMcpProxyCall", () => {
  it("renders a bare mcp call", () => {
    expect(renderText(renderMcpProxyCall({}, fakeTheme, false))).toBe("mcp");
  });

  it("renders a search call", () => {
    expect(
      renderText(
        renderMcpProxyCall({ search: "deploy staging" }, fakeTheme, false),
      ),
    ).toBe('mcp search: "deploy staging"');
  });

  it.each([
    ["collapsed", false, "mcp \u2192 mcp_demo_echo"],
    ["collapsed with args", false, 'mcp \u2192 mcp_demo_echo {"text":"hi"}'],
  ])("renders a tool call (%s)", (label, expanded, expected) => {
    const args =
      label === "collapsed with args"
        ? { tool: "mcp_demo_echo", args: '{"text":"hi"}' }
        : { tool: "mcp_demo_echo" };
    expect(renderText(renderMcpProxyCall(args, fakeTheme, expanded))).toBe(
      expected,
    );
  });

  it("renders a tool call's args expanded, pretty-printed", () => {
    const text = renderText(
      renderMcpProxyCall(
        { tool: "mcp_demo_echo", args: '{"text":"hi"}' },
        fakeTheme,
        true,
      ),
    );
    expect(text).toBe('mcp \u2192 mcp_demo_echo\n{\n  "text": "hi"\n}');
  });
});

function hit(overrides: Partial<Hit> = {}): Hit {
  return {
    serverName: "demo",
    description: "Echo text back",
    connected: true,
    score: 1,
    piName: "mcp_demo_echo",
    ...overrides,
  };
}

describe("renderMcpProxyResult", () => {
  it("passes through raw content while partial", () => {
    const text = renderText(
      renderMcpProxyResult(
        { content: [{ type: "text", text: "..." }] },
        resultOptions({ isPartial: true }),
        fakeTheme,
      ),
    );
    expect(text).toBe("...");
  });

  it("passes through raw content when details is missing (defensive fallback)", () => {
    const text = renderText(
      renderMcpProxyResult(
        { content: [{ type: "text", text: "raw" }] },
        resultOptions(),
        fakeTheme,
      ),
    );
    expect(text).toBe("raw");
  });

  describe("search", () => {
    it("shows a header and no lines for zero hits", () => {
      const text = renderText(
        renderMcpProxyResult(
          {
            content: [{ type: "text", text: "mcp: no matching tools..." }],
            details: { kind: "search", query: "xyz", hits: [] },
          },
          resultOptions(),
          fakeTheme,
        ),
      );
      expect(text).toBe('0 results for "xyz"');
    });

    it("lists each hit, marking connected vs not-connected", () => {
      const hits = [
        hit({ piName: "mcp_demo_echo", connected: true }),
        hit({
          piName: "mcp_demo_other",
          connected: false,
          description: "Other tool",
        }),
        hit({
          piName: undefined,
          serverName: "lazy-server",
          description: "Not connected yet",
        }),
      ];
      const text = renderText(
        renderMcpProxyResult(
          {
            content: [{ type: "text", text: "..." }],
            details: { kind: "search", query: "echo", hits },
          },
          resultOptions(),
          fakeTheme,
        ),
      );
      const lines = text.split("\n");
      expect(lines[0]).toBe('3 results for "echo"');
      expect(lines[1]).toContain("mcp_demo_echo");
      expect(lines[1]).not.toContain("not connected");
      expect(lines[2]).toContain("mcp_demo_other");
      expect(lines[2]).toContain("(not connected)");
      expect(lines[3]).toContain("lazy-server");
      expect(lines[3]).toContain("(server, not connected)");
    });

    it("collapses beyond 6 hits with a count, and shows all when expanded", () => {
      const hits = Array.from({ length: 10 }, (_, i) =>
        hit({ piName: `mcp_demo_tool_${i}`, description: `tool ${i}` }),
      );
      const collapsed = renderText(
        renderMcpProxyResult(
          { content: [], details: { kind: "search", query: "tool", hits } },
          resultOptions({ expanded: false }),
          fakeTheme,
        ),
      );
      const collapsedLines = collapsed.split("\n");
      // header + 6 hits + "...and N more" footer
      expect(collapsedLines).toHaveLength(1 + 6 + 1);
      expect(collapsedLines.at(-1)).toContain("4 more");

      const expanded = renderText(
        renderMcpProxyResult(
          { content: [], details: { kind: "search", query: "tool", hits } },
          resultOptions({ expanded: true }),
          fakeTheme,
        ),
      );
      // header + all 10 hits, no truncation footer
      expect(expanded.split("\n")).toHaveLength(1 + 10);
    });
  });

  describe("connect", () => {
    it("shows tool count on success", () => {
      const text = renderText(
        renderMcpProxyResult(
          {
            content: [],
            details: { kind: "connect", server: "posthog", toolCount: 651 },
          },
          resultOptions(),
          fakeTheme,
        ),
      );
      expect(text).toContain("connected to posthog");
      expect(text).toContain("651 tools");
    });

    it("flags when no tools were reported", () => {
      const text = renderText(
        renderMcpProxyResult(
          {
            content: [],
            details: { kind: "connect", server: "demo", toolCount: 0 },
          },
          resultOptions(),
          fakeTheme,
        ),
      );
      expect(text).toContain("no tools reported");
    });
  });

  describe("call", () => {
    it("shows the dispatched server/tool header plus output", () => {
      const text = renderText(
        renderMcpProxyResult(
          {
            content: [{ type: "text", text: "echo: hi" }],
            details: {
              kind: "call",
              server: "demo",
              tool: "echo",
              piName: "mcp_demo_echo",
            },
          },
          resultOptions(),
          fakeTheme,
        ),
      );
      expect(text).toBe("demo \u2192 echo\necho: hi");
    });

    it("truncates long output when collapsed, shows it all expanded", () => {
      const bigOutput = Array.from({ length: 30 }, (_, i) => `line ${i}`).join(
        "\n",
      );
      const details = {
        kind: "call" as const,
        server: "demo",
        tool: "dump",
        piName: "mcp_demo_dump",
      };

      const collapsed = renderText(
        renderMcpProxyResult(
          { content: [{ type: "text", text: bigOutput }], details },
          resultOptions({ expanded: false }),
          fakeTheme,
        ),
      );
      expect(collapsed).toContain("line 0");
      expect(collapsed).not.toContain("line 29");
      expect(collapsed).toContain("output truncated");

      const expanded = renderText(
        renderMcpProxyResult(
          { content: [{ type: "text", text: bigOutput }], details },
          resultOptions({ expanded: true }),
          fakeTheme,
        ),
      );
      expect(expanded).toContain("line 29");
      expect(expanded).not.toContain("truncated");
    });
  });

  describe("error / no-config / usage", () => {
    it("renders an error message", () => {
      const text = renderText(
        renderMcpProxyResult(
          {
            content: [{ type: "text", text: "mcp: boom" }],
            details: { kind: "error", message: "mcp: boom" },
          },
          resultOptions(),
          fakeTheme,
        ),
      );
      expect(text).toBe("mcp: boom");
    });

    it.each([["no-config"], ["usage"]] as const)(
      "renders %s from the raw content text",
      (kind) => {
        const text = renderText(
          renderMcpProxyResult(
            {
              content: [
                { type: "text", text: "mcp: no MCP servers configured." },
              ],
              details: { kind },
            },
            resultOptions(),
            fakeTheme,
          ),
        );
        expect(text).toBe("mcp: no MCP servers configured.");
      },
    );
  });
});
