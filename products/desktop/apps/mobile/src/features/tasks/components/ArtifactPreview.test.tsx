import type { TaskRunArtifact } from "@posthog/shared";
import { createElement } from "react";
import WebView from "react-native-webview";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { ArtifactPreview } from "./ArtifactPreview";

const mockPreview = vi.fn();
const mockQuery = vi.fn();

vi.mock("../hooks/useCloudAttachmentPreview", () => ({
  useCloudAttachmentPreview: () => mockPreview(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => mockQuery(),
}));

vi.mock("react-native-webview", () => ({
  default: (props: Record<string, unknown>) => createElement("WebView", props),
}));

vi.mock("@/features/mcp/sandbox/mcpAppCsp", () => ({
  applyCspToHtml: (html: string) => `csp:${html}`,
}));

vi.mock("@/features/chat", () => ({
  MarkdownText: (props: Record<string, unknown>) =>
    createElement("MarkdownText", props),
}));

vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 9: "#999", 11: "#555", 12: "#111" },
    accent: { 9: "#f54d00" },
  }),
}));

// The global react-native mock renders Modal through a DOM portal that is a
// no-op under the node test env, so its children never mount. Substitute plain
// host elements for the components the preview uses so the body is inspectable.
vi.mock("react-native", () => {
  const host = (name: string) => (props: Record<string, unknown>) =>
    createElement(name, props);
  return {
    ActivityIndicator: host("ActivityIndicator"),
    Image: host("Image"),
    Modal: host("Modal"),
    Pressable: host("Pressable"),
    ScrollView: host("ScrollView"),
    Text: host("Text"),
    View: host("View"),
  };
});

function mount() {
  mockPreview.mockReturnValue({
    data: "https://s3.example/report.html",
    isLoading: false,
  });
  mockQuery.mockReturnValue({
    data: "<h1>hello</h1>",
    isLoading: false,
    isError: false,
  });
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(
      createElement(ArtifactPreview, {
        taskId: "t1",
        runId: "r1",
        artifact: {
          id: "a1",
          name: "report.html",
          type: "output",
        } as TaskRunArtifact,
        onClose: vi.fn(),
      }),
    );
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function webViews(renderer: ReturnType<typeof create>) {
  return renderer.root.findAll((node) => node.type === WebView);
}

describe("ArtifactPreview", () => {
  it("runs HTML artifacts with scripts enabled and the CSP applied", () => {
    const renderer = mount();
    const rendered = webViews(renderer);
    expect(rendered).toHaveLength(1);
    expect(rendered[0].props.javaScriptEnabled).toBe(true);
    expect(rendered[0].props.setSupportMultipleWindows).toBe(false);
    expect(rendered[0].props.source).toEqual({ html: "csp:<h1>hello</h1>" });
  });

  it("stops the preview by unmounting the web content and restarts it", () => {
    const renderer = mount();
    expect(webViews(renderer)).toHaveLength(1);

    const stop = renderer.root.findByProps({
      accessibilityLabel: "Stop preview",
    });
    act(() => {
      stop.props.onPress();
    });
    expect(webViews(renderer)).toHaveLength(0);
    expect(JSON.stringify(renderer.toJSON())).toContain("Preview stopped");

    const restart = renderer.root.findByProps({
      accessibilityLabel: "Restart preview",
    });
    act(() => {
      restart.props.onPress();
    });
    expect(webViews(renderer)).toHaveLength(1);
  });
});
