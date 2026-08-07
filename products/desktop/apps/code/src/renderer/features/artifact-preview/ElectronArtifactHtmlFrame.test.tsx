import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ElectronArtifactHtmlFrame } from "./ElectronArtifactHtmlFrame";

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
});
