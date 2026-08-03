import path from "node:path";
import { fileURLToPath } from "node:url";
import { isSafeExternalUrl } from "@posthog/shared";
import { type BrowserWindow, type Session, shell } from "electron";
import { logger } from "./utils/logger";

const log = logger.scope("external-links");

function urlScheme(url: string): string {
  try {
    return new URL(url).protocol;
  } catch {
    return "<unparseable>";
  }
}

// `shell.openExternal` dispatches to whatever app the OS registered for the
// scheme, so it must never receive a scheme outside the http/https/mailto
// allowlist: renderer content (including sandboxed MCP apps) can reach these
// handlers via window.open/navigation with e.g. smb:, file:, or ms-msdt: URLs.
function openExternalIfSafe(url: string): void {
  if (!isSafeExternalUrl(url)) {
    log.warn("Blocked externally-opened URL with disallowed scheme", {
      scheme: urlScheme(url),
    });
    return;
  }
  // openExternal rejects when the OS has no handler for the scheme (or the user
  // dismisses the confirmation prompt on some platforms). Swallow it so a failed
  // open never surfaces as an unhandled rejection in the main process.
  shell.openExternal(url).catch((error) => {
    log.warn("shell.openExternal rejected", { scheme: urlScheme(url), error });
  });
}

function isInAppNavigation(target: string, appHome: URL): boolean {
  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return false;
  }

  if (appHome.protocol === "file:") {
    if (parsed.protocol !== "file:") return false;
    if (parsed.host !== appHome.host) return false;

    try {
      const appEntryPath = fileURLToPath(appHome);
      const targetPath = fileURLToPath(parsed);
      return path.relative(appEntryPath, targetPath) === "";
    } catch {
      return false;
    }
  }

  // Dev server (http/https): pin scheme + host + port exactly.
  return parsed.origin === appHome.origin;
}

function isAllowedSubframeNavigation(target: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return false;
  }

  if (parsed.protocol === "mcp-sandbox:") {
    return parsed.host === "proxy";
  }

  if (parsed.protocol === "about:") {
    return parsed.pathname === "blank" || parsed.pathname === "srcdoc";
  }

  return ["http:", "https:", "blob:", "data:"].includes(parsed.protocol);
}

export function setupExternalLinkPermissionHandlers(session: Session): void {
  // Electron approves permission requests by default. Preserve that existing
  // behavior except for renderer-initiated external application launches,
  // which must go through the validated host launcher instead.
  session.setPermissionCheckHandler(
    (_webContents, permission) => permission !== "openExternal",
  );
  session.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission !== "openExternal");
  });
}

export function setupExternalLinkHandlers(
  window: BrowserWindow,
  appHome: URL,
): void {
  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternalIfSafe(url);
    return { action: "deny" };
  });

  window.webContents.on("will-navigate", (event, url) => {
    if (isInAppNavigation(url, appHome)) return;
    event.preventDefault();
    openExternalIfSafe(url);
  });

  window.webContents.on("will-frame-navigate", (event) => {
    if (event.isMainFrame || isAllowedSubframeNavigation(event.url)) return;
    event.preventDefault();
    log.warn("Blocked subframe navigation with unsupported scheme", {
      scheme: urlScheme(event.url),
    });
  });
}
