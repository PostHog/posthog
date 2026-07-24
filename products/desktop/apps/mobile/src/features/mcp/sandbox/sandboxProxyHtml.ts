/**
 * Sandbox proxy HTML for mobile MCP Apps.
 *
 * Mirrors the desktop double-iframe pattern (see
 * apps/code/src/shared/mcp-sandbox-proxy.html) but routes messages through
 * `react-native-webview`'s bridge instead of `window.parent.postMessage`.
 *
 *   RN host  ←→  WebView (this HTML, the outer "proxy")  ←→  Inner iframe (MCP App)
 *
 * Wire format on both sides is JSON-RPC, identical to desktop. The differences
 * are only in how messages cross the boundary:
 *
 *   - Inbound (RN → WebView): RN calls `window.__mcpReceive(jsonString)` via
 *     `webView.injectJavaScript`.
 *   - Outbound (WebView → RN): the proxy calls
 *     `window.ReactNativeWebView.postMessage(jsonString)`.
 *
 * The inner iframe still uses standard `window.parent.postMessage` to reach
 * the proxy — that part doesn't change.
 */
export const sandboxProxyHtml = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
  <style>
    html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }
    iframe { border: none; width: 100%; height: 100%; display: block; }
  </style>
</head>
<body>
<script>
(function () {
  "use strict";

  function postToHost(data) {
    try {
      window.ReactNativeWebView.postMessage(JSON.stringify(data));
    } catch (err) {
      // Best-effort; nothing to do if the bridge is gone.
    }
  }

  function log() {
    var args = Array.prototype.slice.call(arguments);
    postToHost({ jsonrpc: "2.0", method: "ui/notifications/log", params: { args: args } });
  }

  var inner = document.createElement("iframe");
  inner.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
  document.body.appendChild(inner);

  function buildAllowAttribute(permissions) {
    if (!permissions || typeof permissions !== "object") return "";
    var mapping = {
      camera: "camera",
      microphone: "microphone",
      geolocation: "geolocation",
      clipboardWrite: "clipboard-write"
    };
    return Object.keys(permissions)
      .filter(function (k) { return mapping[k] && permissions[k] != null; })
      .map(function (k) { return mapping[k] + " *"; })
      .join("; ");
  }

  // Inbound from RN host. The RN side injects:
  //   window.__mcpReceive(JSON.stringify(message))
  window.__mcpReceive = function (jsonString) {
    var data;
    try { data = JSON.parse(jsonString); } catch (e) { return; }
    if (!data || typeof data !== "object") return;

    if (data.method === "ui/notifications/sandbox-resource-ready") {
      var params = data.params || {};
      if (typeof params.html === "string") {
        var allowValue = buildAllowAttribute(params.permissions);
        if (allowValue) inner.setAttribute("allow", allowValue);

        var doc = inner.contentDocument;
        if (doc) {
          doc.open();
          doc.write(params.html);
          doc.close();
        }
      }
      return;
    }

    // All other host messages get relayed into the inner iframe untouched.
    if (inner.contentWindow) {
      inner.contentWindow.postMessage(data, location.origin || "*");
    }
  };

  // Inner iframe → relay to RN host.
  window.addEventListener("message", function (event) {
    var data = event.data;
    if (!data || typeof data !== "object") return;
    if (event.source !== inner.contentWindow) return;
    postToHost(data);
  });

  // Tell RN we're ready. Retry a few times — RN may not have attached its
  // onMessage handler yet on first paint.
  var ready = { jsonrpc: "2.0", method: "ui/notifications/sandbox-proxy-ready", params: {} };
  var attempts = 0;
  function announce() {
    attempts++;
    postToHost(ready);
    if (attempts < 4) setTimeout(announce, 50 * attempts);
  }
  announce();
})();
</script>
</body>
</html>`;
