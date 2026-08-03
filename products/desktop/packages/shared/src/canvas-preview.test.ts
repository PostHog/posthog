import { describe, expect, it } from "vitest";
import type { CanvasArtifactFile } from "./canvas-build-contract";
import { renderCanvasPreviewDocument } from "./canvas-preview";

function file(path: string, content: string): CanvasArtifactFile {
  return {
    path,
    content,
    contentHash: "0".repeat(64),
    sizeBytes: content.length,
  };
}

const ARTIFACT: CanvasArtifactFile[] = [
  file(
    "index.html",
    [
      "<!doctype html>",
      "<html>",
      "  <head>",
      '    <link rel="stylesheet" href="./assets/style-abc.css" />',
      "  </head>",
      "  <body>",
      '    <div id="root"></div>',
      '    <script type="module" src="./assets/main-abc.js"></script>',
      "  </body>",
      "</html>",
    ].join("\n"),
  ),
  file(
    "assets/main-abc.js",
    'console.log("built \\u003c/script\\u003e safe");',
  ),
  file("assets/style-abc.css", "#root { padding: 1px; }"),
];

describe("renderCanvasPreviewDocument", () => {
  it("inlines emitted assets into one self-contained document with a CSP", () => {
    const doc = renderCanvasPreviewDocument(ARTIFACT);

    // Everything the iframe needs is in the one document — no asset fetches,
    // no runtime compiler.
    expect(doc).toContain('<script type="module">console.log');
    expect(doc).toContain("<style>#root { padding: 1px; }</style>");
    expect(doc).not.toContain("./assets/main-abc.js");
    expect(doc).not.toContain("./assets/style-abc.css");
    expect(doc).toContain('http-equiv="Content-Security-Policy"');
    expect(doc).toContain("default-src 'none'");
  });

  it("escapes closing tags so inlined code cannot break out of its element", () => {
    const doc = renderCanvasPreviewDocument([
      ARTIFACT[0],
      file("assets/main-abc.js", 'const s = "</script><script>alert(1)";'),
      ARTIFACT[2],
    ]);

    expect(doc).toContain("<\\/script>");
    expect(doc).not.toContain('"</script><script>alert(1)');
  });

  it("returns null when the artifact has no entry html", () => {
    expect(renderCanvasPreviewDocument([ARTIFACT[1]])).toBeNull();
  });
});
