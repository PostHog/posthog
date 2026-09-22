import type { TaskRunArtifact } from "@posthog/shared";
import { createElement } from "react";
import WebView from "react-native-webview";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ArtifactPreview } from "./ArtifactPreview";

const mockPreview = vi.fn();
const mockQuery = vi.fn();
const mockOpenExternalUrl = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useCloudAttachmentPreview", () => ({
  useCloudAttachmentPreview: () => mockPreview(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => mockQuery(),
}));

vi.mock("react-native-webview", () => ({
  default: (props: Record<string, unknown>) => createElement("WebView", props),
}));

vi.mock("@posthog/core/mcp-apps/csp", () => ({
  applyCspToHtml: (html: string) => `csp:${html}`,
}));

vi.mock("@/features/chat", () => ({
  MarkdownText: (props: Record<string, unknown>) =>
    createElement("MarkdownText", props),
}));

vi.mock("@/lib/openExternalUrl", () => ({
  openExternalUrl: mockOpenExternalUrl,
}));

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
  beforeEach(() => {
    mockOpenExternalUrl.mockClear();
  });

  it("runs HTML artifacts with scripts enabled and the CSP applied", () => {
    const renderer = mount();
    const rendered = webViews(renderer);
    expect(rendered).toHaveLength(1);
    expect(rendered[0].props.javaScriptEnabled).toBe(true);
    expect(rendered[0].props.setSupportMultipleWindows).toBe(false);
    const { html } = rendered[0].props.source;
    expect(html.startsWith("csp:")).toBe(true);
    expect(html).toContain("<h1>hello</h1>");
    // The media capture guard runs ahead of the artifact's own markup, since
    // mediaCapturePermissionGrantType below is an iOS-only prop.
    expect(html.indexOf("mediaDevices")).toBeLessThan(
      html.indexOf("<h1>hello</h1>"),
    );
  });

  it("keeps the sandbox sealed around the enabled scripts", () => {
    const webView = webViews(mount())[0].props;
    expect(webView.allowFileAccess).toBe(false);
    expect(webView.allowFileAccessFromFileURLs).toBe(false);
    expect(webView.allowUniversalAccessFromFileURLs).toBe(false);
    expect(webView.geolocationEnabled).toBe(false);
    expect(webView.mediaCapturePermissionGrantType).toBe("deny");
    // No bridge back into the app.
    expect(webView.onMessage).toBeUndefined();
    expect(webView.injectedJavaScript).toBeUndefined();
  });

  it("only lets the artifact's own document load in place", () => {
    const webView = webViews(mount())[0].props;
    expect(
      webView.onShouldStartLoadWithRequest({
        url: "about:blank",
        navigationType: "other",
      }),
    ).toBe(true);
  });

  it("denies navigation that is not a tapped web link", () => {
    const webView = webViews(mount())[0].props;
    for (const url of [
      "tel:+15550100",
      "sms:+15550100",
      "mailto:a@b.c",
      "itms-apps://apps.apple.com/app/id1",
      "myapp://do-thing",
      "data:text/html,<script></script>",
      "file:///etc/passwd",
      "https://evil.example",
    ]) {
      expect(
        webView.onShouldStartLoadWithRequest({ url, navigationType: "other" }),
      ).toBe(false);
    }
    // A non-web scheme is dropped even when it comes from a tap.
    expect(
      webView.onShouldStartLoadWithRequest({
        url: "myapp://do-thing",
        navigationType: "click",
      }),
    ).toBe(false);
    expect(mockOpenExternalUrl).not.toHaveBeenCalled();
  });

  it("opens a tapped web link externally instead of navigating", () => {
    const webView = webViews(mount())[0].props;
    expect(
      webView.onShouldStartLoadWithRequest({
        url: "https://posthog.com",
        navigationType: "click",
      }),
    ).toBe(false);
    expect(mockOpenExternalUrl).toHaveBeenCalledWith("https://posthog.com");
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
