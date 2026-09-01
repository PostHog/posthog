import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { ToolMessage, type ToolMessageProps } from "./ToolMessage";

vi.mock("expo-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("@/features/mcp/components/McpAppHost", () => ({
  McpAppHost: () => null,
}));

vi.mock("@/lib/syntax-highlight", () => ({
  getColorForClass: () => null,
  highlightCode: () => null,
  languageFromPath: () => null,
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 8: "#888888", 9: "#999999", 11: "#bbbbbb", 12: "#cccccc" },
    accent: { 3: "#eef", 9: "#3366ff", contrast: "#ffffff" },
    status: { success: "#00aa00", error: "#cc0000" },
  }),
}));

function render(props: ToolMessageProps) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(ToolMessage, props));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function expand(renderer: ReturnType<typeof create>) {
  const pressable = renderer.root.findAll(
    (n) => typeof n.props?.onPress === "function",
  )[0];
  act(() => {
    pressable.props.onPress();
  });
}

function tree(renderer: ReturnType<typeof create>): string {
  return JSON.stringify(renderer.toJSON());
}

const ERROR_OUTPUT = "Error: query failed: invalid HogQL syntax near token";

const base: ToolMessageProps = {
  toolName: "exec",
  rawToolName: "mcp__posthog__exec",
  status: "error",
  args: { command: "call query-run {}" },
  result: ERROR_OUTPUT,
};

describe("ToolMessage posthog-exec error reason", () => {
  it("hides output in the collapsed state for a failed call", () => {
    const renderer = render(base);
    expect(tree(renderer)).not.toContain(ERROR_OUTPUT);
  });

  it.each<[ToolMessageProps["status"], boolean]>([
    ["error", true],
    ["completed", true],
    ["running", false],
  ])("status=%s → output visible after expand: %s", (status, expectVisible) => {
    const renderer = render({ ...base, status });
    expand(renderer);
    if (expectVisible) {
      expect(tree(renderer)).toContain(ERROR_OUTPUT);
    } else {
      expect(tree(renderer)).not.toContain(ERROR_OUTPUT);
    }
  });
});
