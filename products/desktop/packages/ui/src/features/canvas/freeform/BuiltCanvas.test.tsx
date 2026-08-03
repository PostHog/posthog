import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuiltCanvas } from "./BuiltCanvas";

describe("BuiltCanvas", () => {
  it("loads an immutable artifact without granting origin or popup access", () => {
    render(
      <BuiltCanvas
        artifactUrl="https://usercontent.example/build/index.html"
        onDataRequest={vi.fn()}
      />,
    );

    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "src",
      "https://usercontent.example/build/index.html",
    );
    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "referrerpolicy",
      "no-referrer",
    );
  });

  it("revokes data access when the artifact document navigates", async () => {
    const onDataRequest = vi.fn().mockResolvedValue({ secret: true });
    render(
      <BuiltCanvas
        artifactUrl="https://usercontent.example/build/index.html"
        onDataRequest={onDataRequest}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    if (!iframe.contentWindow) throw new Error("Canvas iframe has no window");
    const postMessage = vi.spyOn(iframe.contentWindow, "postMessage");

    fireEvent.load(iframe);
    const calls = postMessage.mock.calls as unknown as [
      unknown,
      string,
      Transferable[],
    ][];
    const transferredPort = calls[0]?.[2]?.[0];
    expect(transferredPort).toBeInstanceOf(MessagePort);

    fireEvent.load(iframe);
    (transferredPort as MessagePort).postMessage({
      channel: "posthog-canvas",
      type: "data-request",
      id: "request-after-navigation",
      method: "query",
      payload: { hogql: "select 1" },
    });

    await waitFor(() => expect(onDataRequest).not.toHaveBeenCalled());
  });

  it("gates data requests on the manifest's capabilities", async () => {
    const onDataRequest = vi.fn().mockResolvedValue({ rows: [] });
    render(
      <BuiltCanvas
        artifactUrl="https://usercontent.example/build/index.html"
        capabilities={{
          posthog: { insights: [], inlineQueries: false, captureEvents: [] },
          network: { origins: [] },
        }}
        onDataRequest={onDataRequest}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    if (!iframe.contentWindow) throw new Error("Canvas iframe has no window");
    const postMessage = vi.spyOn(iframe.contentWindow, "postMessage");

    fireEvent.load(iframe);
    const calls = postMessage.mock.calls as unknown as [
      unknown,
      string,
      Transferable[],
    ][];
    const canvasPort = calls[0]?.[2]?.[0] as MessagePort;
    const responses: unknown[] = [];
    canvasPort.addEventListener("message", (event) =>
      responses.push((event as MessageEvent).data),
    );
    canvasPort.start();

    canvasPort.postMessage({
      channel: "posthog-canvas",
      type: "data-request",
      id: "gated-query",
      method: "query",
      payload: { hogql: "select 1" },
    });

    await waitFor(() => expect(responses).toHaveLength(1));
    expect(responses[0]).toMatchObject({
      type: "data-response",
      id: "gated-query",
      ok: false,
      error: "Inline queries are not allowed by this canvas",
    });
    expect(onDataRequest).not.toHaveBeenCalled();
  });
});
