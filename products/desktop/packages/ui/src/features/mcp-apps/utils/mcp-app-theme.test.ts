import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildHostStyles, buildHostStylesCss } from "./mcp-app-theme";

// Mock getComputedStyle to return predictable values
const mockStyles = new Map<string, string>([
  ["--gray-1", "#111"],
  ["--gray-2", "#222"],
  ["--gray-3", "#333"],
  ["--gray-5", "#555"],
  ["--gray-6", "#666"],
  ["--gray-10", "#aaa"],
  ["--gray-11", "#bbb"],
  ["--gray-12", "#ccc"],
  ["--accent-3", "#fa3"],
  ["--accent-6", "#f86"],
  ["--accent-9", "#f90"],
  ["--accent-11", "#fb0"],
  ["--red-3", "#f33"],
  ["--red-6", "#f44"],
  ["--red-9", "#f00"],
  ["--red-11", "#f66"],
  ["--green-3", "#3f3"],
  ["--green-6", "#4f4"],
  ["--green-9", "#0f0"],
  ["--green-11", "#6f6"],
  ["--yellow-3", "#ff3"],
  ["--yellow-6", "#ff4"],
  ["--yellow-9", "#ff0"],
  ["--yellow-11", "#ff6"],
  ["--default-font-family", "Berkeley Mono, monospace"],
  ["--code-font-family", "JetBrains Mono, monospace"],
  ["--font-size-1", "12px"],
  ["--font-size-2", "14px"],
  ["--font-size-3", "16px"],
  ["--font-size-4", "18px"],
  ["--font-size-5", "20px"],
  ["--font-size-6", "24px"],
  ["--font-size-7", "28px"],
  ["--font-size-8", "35px"],
  ["--font-size-9", "60px"],
  ["--radius-2", "4px"],
  ["--radius-3", "8px"],
  ["--radius-4", "12px"],
  ["--radius-5", "16px"],
]);

beforeEach(() => {
  vi.stubGlobal("getComputedStyle", () => ({
    getPropertyValue: (name: string) => mockStyles.get(name) ?? "",
  }));

  vi.stubGlobal("document", {
    ...document,
    documentElement: document.documentElement,
    fonts: { check: () => false },
  });
});

describe("buildHostStyles", () => {
  it("returns variables and css objects", () => {
    const result = buildHostStyles(true);
    expect(result).toHaveProperty("variables");
    expect(result).toHaveProperty("css");
    expect(result.css).toHaveProperty("fonts");
  });

  it("includes all required MCP Apps CSS variables", () => {
    const result = buildHostStyles(true);
    const vars = result.variables;

    // Background (all spec-defined)
    expect(vars["--color-background-primary"]).toBeDefined();
    expect(vars["--color-background-secondary"]).toBeDefined();
    expect(vars["--color-background-tertiary"]).toBeDefined();
    expect(vars["--color-background-inverse"]).toBeDefined();
    expect(vars["--color-background-ghost"]).toBe("transparent");
    expect(vars["--color-background-info"]).toBeDefined();
    expect(vars["--color-background-danger"]).toBeDefined();
    expect(vars["--color-background-success"]).toBeDefined();
    expect(vars["--color-background-warning"]).toBeDefined();
    expect(vars["--color-background-disabled"]).toBeDefined();

    // Text (all spec-defined)
    expect(vars["--color-text-primary"]).toBeDefined();
    expect(vars["--color-text-secondary"]).toBeDefined();
    expect(vars["--color-text-tertiary"]).toBeDefined();
    expect(vars["--color-text-inverse"]).toBeDefined();
    expect(vars["--color-text-ghost"]).toBeDefined();
    expect(vars["--color-text-info"]).toBeDefined();
    expect(vars["--color-text-danger"]).toBeDefined();
    expect(vars["--color-text-success"]).toBeDefined();
    expect(vars["--color-text-warning"]).toBeDefined();
    expect(vars["--color-text-disabled"]).toBeDefined();

    // Border (all spec-defined)
    expect(vars["--color-border-primary"]).toBeDefined();
    expect(vars["--color-border-secondary"]).toBeDefined();
    expect(vars["--color-border-tertiary"]).toBeDefined();
    expect(vars["--color-border-inverse"]).toBeDefined();
    expect(vars["--color-border-ghost"]).toBe("transparent");
    expect(vars["--color-border-info"]).toBeDefined();
    expect(vars["--color-border-danger"]).toBeDefined();
    expect(vars["--color-border-success"]).toBeDefined();
    expect(vars["--color-border-warning"]).toBeDefined();
    expect(vars["--color-border-disabled"]).toBeDefined();

    // Ring (all spec-defined)
    expect(vars["--color-ring-primary"]).toBeDefined();
    expect(vars["--color-ring-secondary"]).toBeDefined();
    expect(vars["--color-ring-inverse"]).toBeDefined();
    expect(vars["--color-ring-info"]).toBeDefined();
    expect(vars["--color-ring-danger"]).toBeDefined();
    expect(vars["--color-ring-success"]).toBeDefined();
    expect(vars["--color-ring-warning"]).toBeDefined();

    // Fonts
    expect(vars["--font-sans"]).toBeDefined();
    expect(vars["--font-mono"]).toBeDefined();

    // Font weights
    expect(vars["--font-weight-normal"]).toBe("400");
    expect(vars["--font-weight-medium"]).toBe("500");
    expect(vars["--font-weight-semibold"]).toBe("600");
    expect(vars["--font-weight-bold"]).toBe("700");

    // Font sizes (spec names: xs, sm, md, lg)
    expect(vars["--font-text-xs-size"]).toBeDefined();
    expect(vars["--font-text-sm-size"]).toBeDefined();
    expect(vars["--font-text-md-size"]).toBeDefined();
    expect(vars["--font-text-lg-size"]).toBeDefined();

    // Heading sizes (spec names: xs through 3xl)
    expect(vars["--font-heading-xs-size"]).toBeDefined();
    expect(vars["--font-heading-sm-size"]).toBeDefined();
    expect(vars["--font-heading-md-size"]).toBeDefined();
    expect(vars["--font-heading-lg-size"]).toBeDefined();
    expect(vars["--font-heading-xl-size"]).toBeDefined();
    expect(vars["--font-heading-2xl-size"]).toBeDefined();
    expect(vars["--font-heading-3xl-size"]).toBeDefined();

    // Line heights (all spec-defined)
    expect(vars["--font-text-xs-line-height"]).toBe("1.5");
    expect(vars["--font-text-sm-line-height"]).toBe("1.5");
    expect(vars["--font-text-md-line-height"]).toBe("1.5");
    expect(vars["--font-text-lg-line-height"]).toBe("1.5");
    expect(vars["--font-heading-xs-line-height"]).toBe("1.3");
    expect(vars["--font-heading-sm-line-height"]).toBe("1.3");
    expect(vars["--font-heading-md-line-height"]).toBe("1.25");
    expect(vars["--font-heading-lg-line-height"]).toBe("1.25");
    expect(vars["--font-heading-xl-line-height"]).toBe("1.2");
    expect(vars["--font-heading-2xl-line-height"]).toBe("1.2");
    expect(vars["--font-heading-3xl-line-height"]).toBe("1.1");

    // Border radius
    expect(vars["--border-radius-xs"]).toBeDefined();
    expect(vars["--border-radius-full"]).toBe("9999px");

    // Border width
    expect(vars["--border-width-regular"]).toBe("1px");

    // Shadows
    expect(vars["--shadow-hairline"]).toBeDefined();
    expect(vars["--shadow-sm"]).toBeDefined();
    expect(vars["--shadow-md"]).toBeDefined();
    expect(vars["--shadow-lg"]).toBeDefined();
  });

  it("reads from computed CSS variables", () => {
    const result = buildHostStyles(true);
    expect(result.variables["--color-background-primary"]).toBe("#111");
    expect(result.variables["--color-text-primary"]).toBe("#ccc");
    expect(result.variables["--color-border-info"]).toBe("#f86");
    expect(result.variables["--color-ring-danger"]).toBe("#f00");
  });
});

describe("buildHostStylesCss", () => {
  it("converts variables to CSS string", () => {
    const css = buildHostStylesCss({
      "--color-background-primary": "#111",
      "--color-text-primary": "#ccc",
    });
    expect(css).toContain("--color-background-primary: #111;");
    expect(css).toContain("--color-text-primary: #ccc;");
  });
});
