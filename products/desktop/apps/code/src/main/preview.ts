/**
 * Runtime face of the desktop preview deployment.
 *
 * electron-vite inlines the validated preview manifest as
 * `__DESKTOP_PREVIEW_MANIFEST__` (see electron.vite.config.ts and
 * scripts/preview-config.mts). This module turns that constant into the
 * host-level state bootstrap and the platform adapters read, and is the one
 * place that decides "is this a preview build" (`getPreviewManifest()`).
 *
 * Preview builds stay packaged builds: `app.isPackaged` is true, dev-mode CDP
 * stays off, and no helper flips to development mode. Ordinary builds get
 * `null` everywhere and keep their existing behavior.
 */

import {
  type DesktopPreviewIdentity,
  type DesktopPreviewManifest,
  desktopPreviewIdentity,
  parseDesktopPreviewManifest,
} from "@posthog/shared";

// Inlined by electron-vite `define`; an ordinary build compiles to null.
declare const __DESKTOP_PREVIEW_MANIFEST__: unknown;

type ResolvedPreview = {
  manifest: DesktopPreviewManifest;
  identity: DesktopPreviewIdentity;
};

let cached: ResolvedPreview | null | undefined;

export function getPreviewManifest(): DesktopPreviewManifest | null {
  const resolved = resolve();
  return resolved ? resolved.manifest : null;
}

export function getPreviewIdentity(): DesktopPreviewIdentity | null {
  const resolved = resolve();
  return resolved ? resolved.identity : null;
}

export function isPreviewBuild(): boolean {
  return resolve() !== null;
}

function resolve(): ResolvedPreview | null {
  if (cached !== undefined) {
    return cached;
  }
  const raw =
    typeof __DESKTOP_PREVIEW_MANIFEST__ !== "undefined"
      ? __DESKTOP_PREVIEW_MANIFEST__
      : null;
  if (raw === null) {
    cached = null;
    return null;
  }
  // Fail closed: an invalid inlined manifest means the packaging step and the
  // build config disagree, which must never produce a half-preview app.
  const manifest = parseDesktopPreviewManifest(raw);
  cached = { manifest, identity: desktopPreviewIdentity(manifest) };
  return cached;
}
