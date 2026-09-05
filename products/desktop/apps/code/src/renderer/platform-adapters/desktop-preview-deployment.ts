/**
 * Renderer-side preview deployment binding. The manifest is inlined into the
 * renderer bundle at build time (see electron.vite.config.ts), so the
 * renderer resolves the same validated value the main process holds without a
 * cross-process hop.
 */

import type { PreviewDeploymentInfo } from "@posthog/platform/preview-deployment";
import {
  type DesktopPreviewManifest,
  parseDesktopPreviewManifest,
} from "@posthog/shared";

// Inlined by electron-vite `define`; an ordinary build compiles to null.
declare const __DESKTOP_PREVIEW_MANIFEST__: unknown;

export function resolveRendererPreviewDeployment(): PreviewDeploymentInfo | null {
  const raw =
    typeof __DESKTOP_PREVIEW_MANIFEST__ !== "undefined"
      ? __DESKTOP_PREVIEW_MANIFEST__
      : null;
  if (raw === null) {
    return null;
  }
  const manifest = parseDesktopPreviewManifest(raw as DesktopPreviewManifest);
  return {
    manifest,
    label: `PR ${manifest.prNumber} · ${manifest.commitSha.slice(0, 7)}`,
  };
}
