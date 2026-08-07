import { describe, expect, it } from "vitest";
import { removeAutomaticRedirects } from "./artifactHtml";

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
