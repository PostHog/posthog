# OS shell

With the `os-shell` flag (`FEATURE_FLAGS.OS_SHELL`) on, the app renders an OS-style desktop in place of the regular layout.
Users stay on the regular URLs.
The current URL opens as the focused window, and each window is an iframe of the app in framed mode.
With the flag off, nothing here renders.

## How the switch works

- `navigation3000Logic.mode` resolves through `resolveOsShellMode` (`osShellMode.ts`).
  It returns `os` when the flag is on and the page would show the regular layout, and `framed` inside an OS window.
- `AuthenticatedShell` renders `shell/OsShell` for `os`, and `Navigation` for every other mode.
- `Navigation` renders only the scene for `framed`: no navigation, no side panel, no top bar.
- A page is framed when `isOsFrame(window)` is true (`bridge/osFrame.ts`).
  An OS window names its frame with `osFrameName(windowId)`, and the frame keeps that name across navigations and reloads.
  Nothing is written to localStorage, and a framed page never renders the OS shell again.
- `/os` (`Scene.Os`, `urls.os()`) is reserved for a design-variant prototype.
  With the flag on it shows the desktop without a window, and otherwise it shows the not-found page.
- The backend lets the app frame itself with `frame-ancestors 'self'` in `CSPMiddleware` (`posthog/middleware.py`).

## Folder ownership

Each folder belongs to one ticket, so parallel work does not touch the same files.
There is no shared `osLogic`: each folder owns its own logic, and `shell/OsShell.tsx` composes them.

| Folder     | Owns                                                                        | Notes                                                               |
| ---------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `shell/`   | Desktop, menu bar, desktop icons, wallpapers, theme, and `OsShell` itself   | `OsShell` is a placeholder that opens the current URL in a window.  |
| `windows/` | Window manager: open, focus, z-order, drag, resize, snap, minimize, tidy up | `OsWindow` is a placeholder frame with a title bar.                 |
| `dock/`    | The dock                                                                    |                                                                     |
| `store/`   | App Store and the installed-apps list                                       |                                                                     |
| `bridge/`  | Messages between a framed app and the OS, and framed-mode detection         | Always build a frame `src` with `osFrameSrc`, never from raw input. |

The root files (`OsScene.tsx`, `osShellMode.ts`, this README) belong to the foundation and change only when the switch itself changes.
