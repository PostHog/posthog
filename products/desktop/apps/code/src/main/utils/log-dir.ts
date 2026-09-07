import os from "node:os";
import { join } from "node:path";
import { getPreviewIdentity } from "../preview";
import { isDevBuild } from "./env";

/**
 * The per-build log root under ~/.posthog-code. A preview build runs beside
 * the production install (its single-instance lock keys off the preview slug),
 * so it must not write into the shared production `logs/` folder: both apps
 * would interleave lines and rotate each other's files.
 */
export function logDir(): string {
  const previewSlug = getPreviewIdentity()?.slug;
  const isDev = process.env.NODE_ENV === "development" || isDevBuild();
  return join(
    os.homedir(),
    ".posthog-code",
    previewSlug ? `logs-${previewSlug}` : isDev ? "logs-dev" : "logs",
  );
}
