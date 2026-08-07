import { describe, expect, it } from "vitest";
import { removeAutomaticRedirects } from "./artifactHtml";

describe("removeAutomaticRedirects", () => {
  it.each([
    ['<meta http-equiv="refresh" content="0;url=https://evil.example">'],
    ['<META HTTP-EQUIV="REFRESH" CONTENT="5">'],
    ["<meta http-equiv='refresh' content='0'>"],
    ['<meta content="0;url=/next" http-equiv="refresh">'],
    ['<meta   http-equiv =  "refresh"   content="0">'],
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
  ])("keeps non-refresh markup untouched %#", (meta) => {
    const html = `<!doctype html><head>${meta}</head>`;
    expect(removeAutomaticRedirects(html)).toBe(html);
  });
});
