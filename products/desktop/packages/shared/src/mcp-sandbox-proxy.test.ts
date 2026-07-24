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

  it("creates inner iframe with allow-scripts, allow-same-origin, and allow-forms sandbox", () => {
    expect(sandboxProxyHtml).toContain(
      "allow-scripts allow-same-origin allow-forms",
    );
  });

  it("uses document.write to inject HTML instead of srcdoc", () => {
    expect(sandboxProxyHtml).toContain("doc.open()");
    expect(sandboxProxyHtml).toContain("doc.write(params.html)");
    expect(sandboxProxyHtml).toContain("doc.close()");
  });

  it("uses location.origin for forwarding messages to inner iframe", () => {
    expect(sandboxProxyHtml).toContain("postMessage(data, location.origin)");
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
