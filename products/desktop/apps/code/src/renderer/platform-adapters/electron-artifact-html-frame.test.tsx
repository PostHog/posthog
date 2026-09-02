import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ARTIFACT_PREVIEW_DATA_URL_PREFIX } from "../../shared/constants";
import {
  artifactPreviewDataUrl,
  ElectronArtifactHtmlFrame,
} from "./electron-artifact-html-frame";

vi.mock("@posthog/quill", () => ({
  Button: ({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
  Text: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));

describe("ElectronArtifactHtmlFrame", () => {
  it("encodes Unicode HTML with bounded base64 expansion", () => {
    const html = "<h1>Résumé 📈</h1>";
    const url = artifactPreviewDataUrl(html);
    const binary = atob(url.slice(ARTIFACT_PREVIEW_DATA_URL_PREFIX.length));
    const decoded = new TextDecoder().decode(
      Uint8Array.from(binary, (character) => character.charCodeAt(0)),
    );

    expect(decoded).toBe(html);
    expect(url.length - ARTIFACT_PREVIEW_DATA_URL_PREFIX.length).toBeLessThan(
      new TextEncoder().encode(html).length * 2,
    );
  });

  it("destroys and recreates the guest from trusted preview controls", async () => {
    const send = vi.fn();
    const message = { marker: "bridge", type: "comments" };
    const { container } = render(
      <ElectronArtifactHtmlFrame
        document="<script>while (false) {}</script>"
        fallbackDocument="<h1>Static fallback</h1>"
        name="report.html"
        messages={[message]}
        onMessage={vi.fn()}
        onOpenExternal={vi.fn()}
      />,
    );

    const webview = await waitFor(() => {
      const element = container.querySelector("webview");
      if (!element) throw new Error("Expected the artifact webview to mount");
      return element;
    });
    Object.assign(webview, { send });
    act(() => webview.dispatchEvent(new Event("dom-ready")));
    expect(send).toHaveBeenCalledWith("posthog-artifact-host-message", message);

    fireEvent.click(screen.getByText("Stop preview"));
    expect(container.querySelector("webview")).toBeNull();

    fireEvent.click(screen.getByText("Restart preview"));
    await waitFor(() =>
      expect(container.querySelector("webview")).toBeTruthy(),
    );
  });

  it("keeps a working preview mounted when a subresource is blocked", async () => {
    const { container } = render(
      <ElectronArtifactHtmlFrame
        document="<img src='https://example.com/report.png'>"
        fallbackDocument=""
        name="report.html"
        messages={[]}
        onMessage={vi.fn()}
        onOpenExternal={vi.fn()}
      />,
    );
    const webview = await waitFor(() => {
      const element = container.querySelector("webview");
      if (!element) throw new Error("Expected the artifact webview to mount");
      return element;
    });

    const blockedSubresource = new Event("did-fail-load");
    Object.assign(blockedSubresource, {
      errorCode: -20,
      isMainFrame: false,
    });
    act(() => webview.dispatchEvent(blockedSubresource));
    expect(container.querySelector("webview")).toBe(webview);

    const abortedNavigation = new Event("did-fail-load");
    Object.assign(abortedNavigation, { errorCode: -3, isMainFrame: true });
    act(() => webview.dispatchEvent(abortedNavigation));
    expect(container.querySelector("webview")).toBe(webview);

    const failedMainDocument = new Event("did-fail-load");
    Object.assign(failedMainDocument, {
      errorCode: -105,
      isMainFrame: true,
    });
    act(() => webview.dispatchEvent(failedMainDocument));
    expect(container.querySelector("webview")).toBeNull();
    expect(screen.getByText("Restart preview")).toBeInTheDocument();
  });

  it("updates the preview label without recreating the guest", async () => {
    const props = {
      document: "<h1>Report</h1>",
      fallbackDocument: "",
      messages: [],
      onMessage: vi.fn(),
      onOpenExternal: vi.fn(),
    };
    const { container, rerender } = render(
      <ElectronArtifactHtmlFrame {...props} name="report.html" />,
    );
    const webview = await waitFor(() => {
      const element = container.querySelector("webview");
      if (!element) throw new Error("Expected the artifact webview to mount");
      return element;
    });

    rerender(<ElectronArtifactHtmlFrame {...props} name="summary.html" />);

    expect(container.querySelector("webview")).toBe(webview);
    expect(webview).toHaveAttribute("aria-label", "Preview of summary.html");
  });

  it("opens links only through the trusted preload channel", async () => {
    const onMessage = vi.fn();
    const onOpenExternal = vi.fn();
    const { container } = render(
      <ElectronArtifactHtmlFrame
        document="<a href='https://example.com'>Report</a>"
        fallbackDocument=""
        name="report.html"
        messages={[]}
        onMessage={onMessage}
        onOpenExternal={onOpenExternal}
      />,
    );
    const webview = await waitFor(() => {
      const element = container.querySelector("webview");
      if (!element) throw new Error("Expected the artifact webview to mount");
      return element;
    });

    const spoofed = new Event("ipc-message");
    Object.assign(spoofed, {
      channel: "posthog-artifact-message",
      args: [{ type: "open-external", href: "https://example.com/spoof" }],
    });
    act(() => webview.dispatchEvent(spoofed));
    expect(onOpenExternal).not.toHaveBeenCalled();
    expect(onMessage).not.toHaveBeenCalled();

    const trusted = new Event("ipc-message");
    Object.assign(trusted, {
      channel: "posthog-artifact-open-external",
      args: ["https://example.com/report"],
    });
    act(() => webview.dispatchEvent(trusted));
    expect(onOpenExternal).toHaveBeenCalledWith("https://example.com/report");
  });
});
