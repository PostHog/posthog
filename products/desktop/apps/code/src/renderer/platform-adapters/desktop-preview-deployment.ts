import {
  parseDesktopPreviewManifest,
  registerPreviewDeployment,
} from "@posthog/shared";

// Inlined by electron-vite `define`; an ordinary build compiles to null. The
// renderer registers the same validated value the main process holds.
declare const __DESKTOP_PREVIEW_MANIFEST__: unknown;

const raw =
  typeof __DESKTOP_PREVIEW_MANIFEST__ !== "undefined"
    ? __DESKTOP_PREVIEW_MANIFEST__
    : null;
if (raw !== null) {
  registerPreviewDeployment(parseDesktopPreviewManifest(raw));
}
