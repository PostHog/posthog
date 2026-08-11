import { describe, expect, it } from "vitest";
import { denyMediaCapture, removeAutomaticRedirects } from "./artifactHtml";

describe("removeAutomaticRedirects", () => {
  it.each([
    ['<meta http-equiv="refresh" content="0;url=https://evil.example">'],
    ['<META HTTP-EQUIV="REFRESH" CONTENT="5">'],
    ["<meta http-equiv='refresh' content='0'>"],
    ['<meta content="0;url=/next" http-equiv="refresh">'],
    ['<meta   http-equiv =  "refresh"   content="0">'],
    ["<meta http-equiv=refresh content=0>"],
    ['<meta http-equiv="refresh" content="0"/>'],
    // A quoted ">" does not end the tag for an HTML tokenizer, so it must not
    // end it for this helper either.
    ['<meta title=">" http-equiv="refresh" content="0;url=/evil">'],
  ])("strips the auto-refresh meta %#", (meta) => {
    const html = `<!doctype html><html><head>${meta}<title>t</title></head><body><script>ok()</script></body></html>`;
    const result = removeAutomaticRedirects(html);
    expect(result.toLowerCase()).not.toContain("http-equiv");
    expect(result).toContain("<title>t</title>");
    expect(result).toContain("<script>ok()</script>");
  });

  it.each([
    ['<meta charset="utf-8">'],
    ['<meta http-equiv="content-type" content="text/html; charset=utf-8">'],
    ['<meta name="viewport" content="width=device-width, initial-scale=1">'],
    // http-equiv is read as an attribute, not matched as loose tag text, so a
    // value that merely mentions it is left alone.
    ['<meta name="note" content="http-equiv=refresh">'],
  ])("keeps non-refresh markup untouched %#", (meta) => {
    const html = `<!doctype html><head>${meta}</head>`;
    expect(removeAutomaticRedirects(html)).toBe(html);
  });

  it("strips every auto-refresh meta in the document", () => {
    const refresh = '<meta http-equiv="refresh" content="0">';
    const html = `<head><meta charset="utf-8">${refresh}${refresh}</head>`;
    expect(removeAutomaticRedirects(html)).toBe(
      '<head><meta charset="utf-8"></head>',
    );
  });
});

describe("denyMediaCapture", () => {
  // The guard is the whole output when there is no artifact markup to wrap.
  const guardScript = () => {
    const guard = denyMediaCapture("");
    return guard.slice("<script>".length, guard.length - "</script>".length);
  };

  it("runs the guard ahead of the artifact's own markup", () => {
    const result = denyMediaCapture("<body><script>ok()</script></body>");
    expect(result.indexOf("mediaDevices")).toBeLessThan(
      result.indexOf("<body>"),
    );
  });

  it("keeps the doctype first so the document stays out of quirks mode", () => {
    const result = denyMediaCapture("<!doctype html><html></html>");
    expect(result.startsWith("<!doctype html><script>")).toBe(true);
    expect(result.endsWith("<html></html>")).toBe(true);
  });

  it("removes the media capture entry points beyond recovery", () => {
    const fakeNavigator: Record<string, unknown> = {
      mediaDevices: { getUserMedia: () => undefined },
      getUserMedia: () => undefined,
      webkitGetUserMedia: () => undefined,
      mozGetUserMedia: () => undefined,
    };
    new Function("navigator", guardScript())(fakeNavigator);

    for (const key of [
      "mediaDevices",
      "getUserMedia",
      "webkitGetUserMedia",
      "mozGetUserMedia",
    ]) {
      expect(fakeNavigator[key]).toBeUndefined();
      // Non-writable and non-configurable, so artifact scripts cannot put the
      // API back once the guard has run.
      const descriptor = Object.getOwnPropertyDescriptor(fakeNavigator, key);
      expect(descriptor?.writable).toBe(false);
      expect(descriptor?.configurable).toBe(false);
    }
  });

  it("does not throw when an entry point is already missing", () => {
    const fakeNavigator: Record<string, unknown> = {};
    expect(() =>
      new Function("navigator", guardScript())(fakeNavigator),
    ).not.toThrow();
    expect(fakeNavigator.mediaDevices).toBeUndefined();
  });

  // Records the limitation documented in artifactHtml.ts as something the
  // suite states rather than a claim in a comment: the guard reaches one
  // realm's navigator, so a script that builds a fresh realm (an about:blank
  // iframe, which frame-src 'none' does not cover) finds an unpatched one
  // there. Closing that needs a native WebChromeClient denying
  // onPermissionRequest, not a bigger script.
  it("only covers the realm it runs in", () => {
    const topRealmNavigator: Record<string, unknown> = {
      mediaDevices: { getUserMedia: () => undefined },
    };
    const freshRealmNavigator: Record<string, unknown> = {
      mediaDevices: { getUserMedia: () => undefined },
    };
    new Function("navigator", guardScript())(topRealmNavigator);

    expect(topRealmNavigator.mediaDevices).toBeUndefined();
    expect(freshRealmNavigator.mediaDevices).toBeDefined();
  });
});
