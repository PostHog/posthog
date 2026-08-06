import { useThemeStore } from "@posthog/ui/shell/themeStore";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BuiltCanvas } from "./BuiltCanvas";

describe("BuiltCanvas", () => {
  const capabilities = {
    posthog: { insights: [], inlineQueries: false, captureEvents: [] },
    network: { origins: [] },
  };
  const initialIsDarkMode = useThemeStore.getState().isDarkMode;
  afterEach(() => useThemeStore.setState({ isDarkMode: initialIsDarkMode }));

  it("loads an immutable artifact without granting origin or popup access", () => {
    render(
      <BuiltCanvas
        artifactUrl="https://usercontent.example/build/index.html"
        capabilities={capabilities}
        onDataRequest={vi.fn()}
      />,
    );

    const hostDocument = screen.getByTitle("Canvas").getAttribute("srcdoc");
    expect(hostDocument).toContain("frame-src https://usercontent.example");
    expect(hostDocument).toContain(
      'artifactFrame.src = "https://usercontent.example/build/index.html#theme=light"',
    );
    expect(hostDocument).not.toContain("frame-src *");
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
        capabilities={capabilities}
        onDataRequest={onDataRequest}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    if (!iframe.contentWindow) throw new Error("Canvas iframe has no window");
    const postMessage = vi
      .spyOn(iframe.contentWindow, "postMessage")
      .mockImplementation(() => undefined);

    fireEvent.load(iframe);
    const calls = postMessage.mock.calls as unknown as [
      unknown,
      string,
      Transferable[],
    ][];
    const transferredPort = calls.at(-1)?.[2]?.[0];
    expect(transferredPort).toBeInstanceOf(MessagePort);

    window.dispatchEvent(
      new MessageEvent("message", {
        source: iframe.contentWindow,
        data: {
          channel: "posthog-canvas-host",
          type: "artifact-navigation",
        },
      }),
    );
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
        capabilities={capabilities}
        onDataRequest={onDataRequest}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    if (!iframe.contentWindow) throw new Error("Canvas iframe has no window");
    const postMessage = vi
      .spyOn(iframe.contentWindow, "postMessage")
      .mockImplementation(() => undefined);

    fireEvent.load(iframe);
    const calls = postMessage.mock.calls as unknown as [
      unknown,
      string,
      Transferable[],
    ][];
    const canvasPort = calls.at(-1)?.[2]?.[0] as MessagePort;
    const responses: unknown[] = [];
    canvasPort.addEventListener("message", (event) => {
      const data = (event as MessageEvent).data as { type?: string };
      if (data?.type === "data-response") responses.push(data);
    });
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

  it("mirrors the host theme over the artifact bridge", async () => {
    act(() => useThemeStore.setState({ isDarkMode: true }));
    render(
      <BuiltCanvas
        artifactUrl="https://usercontent.example/build/index.html"
        capabilities={capabilities}
        onDataRequest={vi.fn()}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    if (!iframe.contentWindow) throw new Error("Canvas iframe has no window");
    expect(iframe.getAttribute("srcdoc")).toContain("#theme=dark");
    expect(iframe.style.colorScheme).toBe("dark");
    const postMessage = vi
      .spyOn(iframe.contentWindow, "postMessage")
      .mockImplementation(() => undefined);

    fireEvent.load(iframe);
    const calls = postMessage.mock.calls as unknown as [
      unknown,
      string,
      Transferable[],
    ][];
    const canvasPort = calls.at(-1)?.[2]?.[0] as MessagePort;
    const frames: unknown[] = [];
    canvasPort.addEventListener("message", (event) =>
      frames.push((event as MessageEvent).data),
    );
    canvasPort.start();

    await waitFor(() => expect(frames).toHaveLength(1));
    expect(frames[0]).toEqual({
      channel: "posthog-canvas",
      type: "set-theme",
      theme: "dark",
    });

    act(() => useThemeStore.setState({ isDarkMode: false }));
    await waitFor(() => expect(frames).toHaveLength(2));
    expect(frames[1]).toEqual({
      channel: "posthog-canvas",
      type: "set-theme",
      theme: "light",
    });
  });
});
