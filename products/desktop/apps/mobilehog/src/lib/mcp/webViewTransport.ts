import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";
import type WebView from "react-native-webview";

/**
 * MCP `Transport` implementation that bridges JSON-RPC messages between the
 * RN host and a `react-native-webview`-hosted sandbox proxy.
 *
 * Inbound (WebView → RN): the caller hands us messages via `acceptIncoming`
 *   (typically called from the WebView's `onMessage` prop).
 * Outbound (RN → WebView): `send` injects a tiny JS snippet that invokes the
 *   sandbox proxy's `window.__mcpReceive` entry point.
 *
 * The transport never validates origin (there isn't a meaningful one inside a
 * WebView) — the host MUST only inject HTML it trusts via `WebView`'s
 * `source`. Since the sandbox proxy HTML is hard-coded in
 * `sandboxProxyHtml.ts` and the inner iframe's content comes from a UI
 * resource the user has already chosen to install, that boundary is fine.
 */
export class WebViewTransport implements Transport {
  private webViewRef: { current: WebView | null };
  private started = false;
  private closed = false;

  onmessage?: (message: JSONRPCMessage) => void;
  onerror?: (error: Error) => void;
  onclose?: () => void;
  // Required by Transport; we honour it but the protocol version is not
  // meaningful at the WebView boundary.
  setProtocolVersion?: (version: string) => void;

  constructor(webViewRef: { current: WebView | null }) {
    this.webViewRef = webViewRef;
  }

  async start(): Promise<void> {
    this.started = true;
  }

  /**
   * Forward a JSON-RPC message from the host to the WebView. Idempotent and
   * safe to call before `start()` — `injectJavaScript` will just no-op until
   * the WebView is mounted.
   */
  async send(message: JSONRPCMessage): Promise<void> {
    if (this.closed) throw new Error("Transport closed");
    const webView = this.webViewRef.current;
    if (!webView) return;
    const json = JSON.stringify(message);
    // The escape pass below is the standard way to embed an already-JSON
    // string inside another script payload — without it, a literal `</script>`
    // sequence in the data could prematurely end the injected snippet.
    const escaped = json.replace(/<\/script>/gi, "<\\/script>");
    const snippet = `void (window.__mcpReceive && window.__mcpReceive(${escaped}));`;
    webView.injectJavaScript(snippet);
  }

  /**
   * Called from the WebView's `onMessage` handler with the raw JSON payload
   * the sandbox proxy posted. Parses, validates shape, and dispatches.
   */
  acceptIncoming(payload: string): void {
    if (this.closed) return;
    if (!this.started) return;
    let message: unknown;
    try {
      message = JSON.parse(payload);
    } catch (err) {
      this.onerror?.(
        err instanceof Error ? err : new Error("Invalid JSON from WebView"),
      );
      return;
    }
    if (!message || typeof message !== "object") return;
    this.onmessage?.(message as JSONRPCMessage);
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.();
  }
}
