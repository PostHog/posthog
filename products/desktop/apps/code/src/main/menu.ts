import { readdirSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AuthService } from "@posthog/core/auth/auth";
import { MCP_APPS_SERVICE } from "@posthog/core/mcp-apps/identifiers";
import type { McpAppsService } from "@posthog/core/mcp-apps/mcp-apps";
import { UI_SERVICE } from "@posthog/core/ui/identifiers";
import type { UIService } from "@posthog/core/ui/ui";
import type { UpdatesService } from "@posthog/core/updates/updates";
import {
  app,
  type BaseWindow,
  BrowserWindow,
  clipboard,
  dialog,
  Menu,
  type MenuItemConstructorOptions,
  shell,
} from "electron";
import { container } from "./di/container";
import { AUTH_SERVICE, UPDATES_SERVICE } from "./di/tokens";
import { isDevBuild } from "./utils/env";
import { getLogFilePath } from "./utils/logger";
import { adjustWindowZoom, ZOOM_STEP } from "./zoom";

function applyZoom(
  window: BaseWindow | undefined,
  delta: number | "reset",
): void {
  if (window instanceof BrowserWindow) adjustWindowZoom(window, delta);
}

function findLatestCrashDump(): string | null {
  const pendingDir = path.join(app.getPath("crashDumps"), "pending");
  let entries: string[];
  try {
    entries = readdirSync(pendingDir);
  } catch {
    return null;
  }
  let latest: { file: string; mtimeMs: number } | null = null;
  for (const name of entries) {
    if (!name.endsWith(".dmp")) continue;
    const full = path.join(pendingDir, name);
    let mtimeMs: number;
    try {
      mtimeMs = statSync(full).mtimeMs;
    } catch {
      continue;
    }
    if (!latest || mtimeMs > latest.mtimeMs) {
      latest = { file: full, mtimeMs };
    }
  }
  return latest?.file ?? null;
}

function getSystemInfo(): string {
  const commit = __BUILD_COMMIT__ ?? "dev";
  const buildDate = __BUILD_DATE__ ?? "dev";
  return [
    `Version: ${app.getVersion()}`,
    `Commit: ${commit}`,
    `Date: ${buildDate}`,
    `Electron: ${process.versions.electron}`,
    `Chromium: ${process.versions.chrome}`,
    `Node.js: ${process.versions.node}`,
    `V8: ${process.versions.v8}`,
    `OS: ${process.platform} ${process.arch} ${os.release()}`,
  ].join("\n");
}

export function buildApplicationMenu(): void {
  const template: MenuItemConstructorOptions[] = [
    buildAppMenu(),
    buildFileMenu(),
    buildEditMenu(),
    buildViewMenu(),
    buildWindowMenu(),
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function buildAppMenu(): MenuItemConstructorOptions {
  return {
    label: "PostHog",
    submenu: [
      {
        label: "About PostHog",
        click: () => {
          const info = getSystemInfo();

          dialog
            .showMessageBox({
              type: "info",
              title: "About PostHog",
              message: "PostHog",
              detail: info,
              buttons: ["Copy", "OK"],
              defaultId: 1,
            })
            .then((result) => {
              if (result.response === 0) {
                clipboard.writeText(info);
              }
            });
        },
      },
      { type: "separator" },
      {
        label: "Settings...",
        accelerator: "CmdOrCtrl+,",
        click: () => {
          container.get<UIService>(UI_SERVICE).openSettings();
        },
      },
      { type: "separator" },
      ...(!isDevBuild()
        ? [
            {
              label: "Check for Updates...",
              click: () => {
                container
                  .get<UpdatesService>(UPDATES_SERVICE)
                  .triggerMenuCheck();
              },
            },
            { type: "separator" as const },
          ]
        : []),
      { role: "hide" as const },
      { role: "hideOthers" as const },
      { role: "unhide" as const },
      { type: "separator" as const },
      { role: "quit" as const },
    ],
  };
}

function buildFileMenu(): MenuItemConstructorOptions {
  return {
    label: "File",
    submenu: [
      {
        label: "New task",
        accelerator: "CmdOrCtrl+N",
        click: () => {
          container.get<UIService>(UI_SERVICE).newTask();
        },
      },
      { type: "separator" },
      {
        label: "Developer",
        submenu: [
          {
            label:
              process.platform === "darwin"
                ? "Show log file in Finder"
                : "Show log file in file manager",
            click: () => {
              shell.showItemInFolder(getLogFilePath());
            },
          },
          {
            label:
              process.platform === "darwin"
                ? "Show crash dumps in Finder"
                : "Show crash dumps in file manager",
            click: () => {
              const latest = findLatestCrashDump();
              if (latest) {
                shell.showItemInFolder(latest);
                return;
              }
              const pendingDir = path.join(
                app.getPath("crashDumps"),
                "pending",
              );
              void shell.openPath(pendingDir).then((err) => {
                if (err) void shell.openPath(app.getPath("crashDumps"));
              });
            },
          },
          ...(isDevBuild()
            ? [
                {
                  label: "Test: terminate renderer (forced shutdown, no fault)",
                  click: () => {
                    const win = BrowserWindow.getFocusedWindow();
                    if (!win) return;
                    win.webContents.forcefullyCrashRenderer();
                  },
                },
                {
                  label: "Test: crash renderer (in-process, EXC_BAD_ACCESS)",
                  click: () => {
                    const win = BrowserWindow.getFocusedWindow();
                    if (!win) return;
                    void win.webContents.executeJavaScript(
                      "window.__posthogTest.crash()",
                    );
                  },
                },
                {
                  label: "Test: abort renderer (in-process, SIGABRT)",
                  click: () => {
                    const win = BrowserWindow.getFocusedWindow();
                    if (!win) return;
                    void win.webContents.executeJavaScript(
                      "window.__posthogTest.abort()",
                    );
                  },
                },
                {
                  label: "Test: crash main process (SIGABRT)",
                  click: () => {
                    process.crash();
                  },
                },
              ]
            : []),
          { type: "separator" },
          {
            label: "Invalidate OAuth token",
            click: () => {
              void container.get<UIService>(UI_SERVICE).invalidateToken();
            },
          },
          {
            label: "Force refresh of OAuth token",
            click: () => {
              container
                .get<AuthService>(AUTH_SERVICE)
                .refreshAccessToken()
                .then(() => {
                  dialog.showMessageBox({
                    type: "info",
                    title: "OAuth Token Refreshed",
                    message: "Access token refreshed successfully.",
                  });
                })
                .catch((err: Error) => {
                  dialog.showMessageBox({
                    type: "error",
                    title: "OAuth Token Refresh Failed",
                    message: err.message,
                  });
                });
            },
          },
          {
            label: "Refresh MCP Apps discovery",
            click: () => {
              container
                .get<McpAppsService>(MCP_APPS_SERVICE)
                .refreshDiscovery()
                .then(() => {
                  dialog.showMessageBox({
                    type: "info",
                    title: "MCP Apps Refreshed",
                    message:
                      "Cleared all cached resources and re-ran discovery.\nCheck logs for details.",
                  });
                })
                .catch((err: Error) => {
                  dialog.showMessageBox({
                    type: "error",
                    title: "MCP Apps Refresh Failed",
                    message: err.message,
                  });
                });
            },
          },
          { type: "separator" },
          {
            label: "Clear application storage",
            click: () => {
              container.get<UIService>(UI_SERVICE).clearStorage();
            },
          },
        ],
      },
    ],
  };
}

function buildEditMenu(): MenuItemConstructorOptions {
  return {
    label: "Edit",
    submenu: [
      { role: "undo" },
      { role: "redo" },
      { type: "separator" },
      { role: "cut" },
      { role: "copy" },
      { role: "paste" },
      { role: "selectAll" },
    ],
  };
}

function buildViewMenu(): MenuItemConstructorOptions {
  return {
    label: "View",
    submenu: [
      {
        label: "Reload",
        accelerator: "CmdOrCtrl+Shift+R",
        click: () => BrowserWindow.getFocusedWindow()?.webContents.reload(),
      },
      {
        label: "Force Reload",
        accelerator: "CmdOrCtrl+Shift+Alt+R",
        click: () =>
          BrowserWindow.getFocusedWindow()?.webContents.reloadIgnoringCache(),
      },
      { role: "toggleDevTools" },
      { type: "separator" },
      {
        label: "Actual Size",
        accelerator: "CmdOrCtrl+0",
        click: (_menuItem, window) => applyZoom(window, "reset"),
      },
      {
        label: "Zoom In",
        accelerator: "CmdOrCtrl+Plus",
        click: (_menuItem, window) => applyZoom(window, ZOOM_STEP),
      },
      // Hidden duplicate so Cmd+= (i.e. Cmd++ without Shift) also zooms in,
      // matching the built-in zoomIn role's dual accelerator.
      {
        label: "Zoom In",
        accelerator: "CmdOrCtrl+=",
        visible: false,
        click: (_menuItem, window) => applyZoom(window, ZOOM_STEP),
      },
      {
        label: "Zoom Out",
        accelerator: "CmdOrCtrl+-",
        click: (_menuItem, window) => applyZoom(window, -ZOOM_STEP),
      },
      { type: "separator" },
      { role: "togglefullscreen" },
      { type: "separator" },
      {
        label: "Reset layout",
        click: () => {
          container.get<UIService>(UI_SERVICE).resetLayout();
        },
      },
    ],
  };
}

function buildWindowMenu(): MenuItemConstructorOptions {
  return { role: "windowMenu" };
}
