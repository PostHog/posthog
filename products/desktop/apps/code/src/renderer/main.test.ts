import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ENTRY = readFileSync(path.join(__dirname, "main.tsx"), "utf-8");
const STATIC_IMPORT = /^import\s+[^\n]*?"([^"]+)";$/gm;

describe("renderer entry", () => {
  it("imports nothing but the stylesheet", () => {
    // Every static import here compiles before the renderer paints, which is
    // what left the window empty for the whole of a cold start. The app has to
    // arrive through the dynamic import below.
    const imports = [...ENTRY.matchAll(STATIC_IMPORT)].map((match) => match[1]);
    expect(imports).toEqual(["@posthog/ui/styles/globals.css"]);
  });

  it("pulls the app in after the first frame, with a timer behind it", () => {
    expect(ENTRY).toContain('import("@renderer/boot")');
    expect(ENTRY).toContain("requestAnimationFrame");
    // A hidden window never gets a frame, so the timer has to load it too.
    expect(ENTRY).toMatch(/setTimeout\(loadApp, \d+\)/);
  });
});
