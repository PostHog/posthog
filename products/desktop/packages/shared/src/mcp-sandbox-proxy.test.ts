import { describe, expect, it } from "vitest";
import { sandboxProxyHtml } from "./mcp-sandbox-proxy";

// The checks here aren't 100% validating what the code is doing, HOWEVER,
// it does validate we're at least considering the different situations
describe("sandboxProxyHtml", () => {
  it("returns valid HTML", () => {
    expect(sandboxProxyHtml).toContain("<!DOCTYPE html>");
    expect(sandboxProxyHtml).toContain("<html>");
    expect(sandboxProxyHtml).toContain("</html>");
  });

  it("sends sandbox-proxy-ready notification on load", () => {
    expect(sandboxProxyHtml).toContain("ui/notifications/sandbox-proxy-ready");
  });

  it("listens for sandbox-resource-ready message", () => {
    expect(sandboxProxyHtml).toContain(
      "ui/notifications/sandbox-resource-ready",
    );
  });

  it("creates inner iframe without allow-same-origin", () => {
    expect(sandboxProxyHtml).toContain(
      'inner.setAttribute("sandbox", "allow-scripts allow-forms")',
    );
  });

  it("uses srcdoc to inject HTML, never document.write", () => {
    expect(sandboxProxyHtml).toContain('inner.setAttribute("srcdoc"');
    expect(sandboxProxyHtml).not.toContain("doc.write(");
  });

  it("forwards to the inner iframe with a wildcard target origin", () => {
    expect(sandboxProxyHtml).toContain('postMessage(data, "*")');
    expect(sandboxProxyHtml).not.toContain(
      "postMessage(data, location.origin)",
    );
  });

  it("builds permission policy allow attribute with cross-origin delegation", () => {
    expect(sandboxProxyHtml).toContain("buildAllowAttribute");
    expect(sandboxProxyHtml).toContain("clipboard-write");

    // Features use " *" suffix for cross-origin delegation
    expect(sandboxProxyHtml).toContain('+ " *"');
  });

  it("relays inner iframe messages back to host", () => {
    expect(sandboxProxyHtml).toContain("inner.contentWindow");
    expect(sandboxProxyHtml).toContain("window.parent.postMessage");
  });

  it("favors var over let/const", () => {
    expect(sandboxProxyHtml).toContain("var ");
    expect(sandboxProxyHtml).not.toContain("let ");
    expect(sandboxProxyHtml).not.toContain("const ");
  });
});

describe("sandboxProxyHtml inner frame navigation", () => {
  it("closes the bridge when the inner frame loads a second time", () => {
    expect(sandboxProxyHtml).toContain(
      'inner.addEventListener("load", onInnerLoad)',
    );
    expect(sandboxProxyHtml).toContain("bridgeClosed = true");
  });

  it("stops forwarding host messages once the bridge is closed", () => {
    expect(sandboxProxyHtml).toContain(
      "if (!bridgeClosed && inner && inner.contentWindow)",
    );
  });

  it("drops messages relayed from a navigated inner frame", () => {
    expect(sandboxProxyHtml).toContain("if (bridgeClosed) {");
  });
});
