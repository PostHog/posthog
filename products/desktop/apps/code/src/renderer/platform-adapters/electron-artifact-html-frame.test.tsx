import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ElectronArtifactHtmlFrame } from "./electron-artifact-html-frame";

vi.mock("@posthog/quill", () => ({
  Button: ({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
  Text: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));

describe("ElectronArtifactHtmlFrame", () => {
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
