// The renderer bundle is about ten megabytes, and a module script runs before
// the renderer paints. Loading it from the entry therefore held the window
// empty for the whole of a cold start. This entry holds the stylesheet, so the
// boot shell in index.html paints styled, and pulls the app in after the first
// frame. Rollup emits the app as its own chunk, so nothing else compiles first.
import "@posthog/ui/styles/globals.css";

const loadApp = (): void => {
  void import("@renderer/boot");
};

// A window that is still hidden gets no animation frames, so a timer backs
// the frame up. Whichever runs first wins; the import resolves once.
requestAnimationFrame(() => setTimeout(loadApp, 0));
setTimeout(loadApp, 500);
