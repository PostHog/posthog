import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebViewTransport } from "./webViewTransport";

type FakeWebView = {
  injectJavaScript: ReturnType<typeof vi.fn>;
};

function makeRef(): { current: FakeWebView } {
  return {
    current: {
      injectJavaScript: vi.fn(),
    },
  };
}

describe("WebViewTransport", () => {
  let ref: { current: FakeWebView };
  let transport: WebViewTransport;

  beforeEach(() => {
    ref = makeRef();
    // Cast through unknown — the real type expects a WebView instance, but
    // we only ever read `injectJavaScript` so the duck-typed fake suffices.
    transport = new WebViewTransport(
      ref as unknown as {
        current: import("react-native-webview").default | null;
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("injects send() payloads as a __mcpReceive call", async () => {
    await transport.start();
    await transport.send({ jsonrpc: "2.0", id: 1, method: "ping" });
    const snippet = ref.current.injectJavaScript.mock.calls[0][0];
    expect(snippet).toContain("window.__mcpReceive");
    expect(snippet).toContain('"method":"ping"');
  });

  it("escapes embedded </script> in payloads", async () => {
    await transport.start();
    await transport.send({
      jsonrpc: "2.0",
      method: "ui/notifications/log",
      params: { html: "</script><img src=x>" },
    });
    const snippet = ref.current.injectJavaScript.mock.calls[0][0];
    expect(snippet).not.toContain("</script>");
    expect(snippet).toContain("<\\/script>");
  });

  it("dispatches incoming messages to onmessage once started", async () => {
    const received: unknown[] = [];
    transport.onmessage = (msg) => {
      received.push(msg);
    };
    await transport.start();
    transport.acceptIncoming(
      JSON.stringify({
        jsonrpc: "2.0",
        method: "ui/notifications/sandbox-proxy-ready",
      }),
    );
    expect(received).toHaveLength(1);
    expect((received[0] as { method: string }).method).toBe(
      "ui/notifications/sandbox-proxy-ready",
    );
  });

  it("ignores incoming messages before start()", () => {
    const received: unknown[] = [];
    transport.onmessage = (msg) => received.push(msg);
    transport.acceptIncoming(JSON.stringify({ jsonrpc: "2.0", method: "x" }));
    expect(received).toHaveLength(0);
  });

  it("calls onerror on malformed JSON", async () => {
    const errors: Error[] = [];
    transport.onerror = (err) => errors.push(err);
    await transport.start();
    transport.acceptIncoming("not-json{");
    expect(errors).toHaveLength(1);
  });

  it("send() after close throws", async () => {
    await transport.start();
    await transport.close();
    await expect(
      transport.send({ jsonrpc: "2.0", method: "x" }),
    ).rejects.toThrow(/closed/i);
  });

  it("close() fires onclose exactly once", async () => {
    const onclose = vi.fn();
    transport.onclose = onclose;
    await transport.close();
    await transport.close();
    expect(onclose).toHaveBeenCalledTimes(1);
  });

  it("send() is a no-op when the WebView ref is null", async () => {
    ref.current = null as unknown as FakeWebView;
    await transport.start();
    await expect(
      transport.send({ jsonrpc: "2.0", method: "x" }),
    ).resolves.toBeUndefined();
  });
});
