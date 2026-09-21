import { describe, expect, it } from "vitest";
import { deferEntryUntilFirstPaint } from "./vite-plugin-first-paint";

const BUILT_HTML = `<!doctype html>
<html lang="en" class="dark">

<head>
  <title>PostHog</title>
  <script type="module" crossorigin src="./assets/main_window-abc.js"></script>
  <link rel="modulepreload" crossorigin href="./assets/chunk-one.js">
  <link rel="modulepreload" crossorigin href="./assets/chunk-two.js">
  <link rel="stylesheet" crossorigin href="./assets/globals.css">
</head>

<body>
  <div id="root">
    <output data-testid="app-loading-shell"></output>
  </div>
</body>

</html>`;

describe("deferEntryUntilFirstPaint", () => {
  const transformed = deferEntryUntilFirstPaint(BUILT_HTML);

  it("takes the bundle out of the parsed document", () => {
    // A module script in the head runs before the renderer paints, which is
    // what left the window empty for the whole of a cold start.
    expect(transformed).not.toContain('<script type="module"');
    expect(transformed).not.toContain('<link rel="modulepreload"');
  });

  it("still loads the bundle and its preloads", () => {
    expect(transformed).toContain("./assets/main_window-abc.js");
    expect(transformed).toContain("./assets/chunk-one.js");
    expect(transformed).toContain("./assets/chunk-two.js");
    expect(transformed).toContain("requestAnimationFrame");
    // An occluded window never gets a frame, so the timer has to load it too.
    expect(transformed).toContain("setTimeout(start, 500)");
  });

  it("keeps the boot shell and the stylesheet that paints it", () => {
    expect(transformed).toContain('data-testid="app-loading-shell"');
    expect(transformed).toContain(
      '<link rel="stylesheet" crossorigin href="./assets/globals.css">',
    );
  });

  it("leaves a page without a module script alone", () => {
    const html = "<html><body><p>no bundle</p></body></html>";
    expect(deferEntryUntilFirstPaint(html)).toBe(html);
  });
});
