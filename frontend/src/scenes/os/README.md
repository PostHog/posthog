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

| Folder       | Owns                                                                        | Notes                                                               |
| ------------ | --------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `shell/`     | Desktop, menu bar, desktop icons, wallpapers, theme, and `OsShell` itself   | `OsShell` renders `windows/OsWindowLayer`.                          |
| `windows/`   | Window manager: open, focus, z-order, drag, resize, snap, minimize, tidy up | See "Windows" below.                                                |
| `dock/`      | The dock                                                                    |                                                                     |
| `store/`     | App Store and the installed-apps list                                       |                                                                     |
| `bridge/`    | Messages between a framed app and the OS, and framed-mode detection         | Always build a frame `src` with `osFrameSrc`, never from raw input. |
| `spotlight/` | The OS spotlight: the app's command menu with results that open in windows  | See "Spotlight" below.                                              |

The root files (`OsScene.tsx`, `osShellMode.ts`, this README) belong to the foundation and change only when the switch itself changes.

## Windows

`windows/osWindowsLogic` owns every open window, and `windows/OsWindowLayer` renders them in the space its parent gives it.
Other folders open and arrange windows through the logic's actions, never through the DOM:

| Action                                           | Effect                                                                                                                     |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `openWindow(path, { newWindow, title, origin })` | Focuses the window that shows `path`, or opens one. `newWindow` always opens another. `origin` is the point it zooms from. |
| `focusWindow(id)`, `restoreWindow(id)`           | Brings a window to the front. Both also un-minimize it.                                                                    |
| `minimizeWindow(id)`, `closeWindow(id)`          | Hides or closes a window. Focus goes to the next window in the stack.                                                      |
| `maximizeWindow(id)`, `unmaximizeWindow(id)`     | Fills the desktop, or goes back to the size before the last maximize or snap.                                              |
| `snapWindow(id, 'left' \| 'right')`              | Fills one half of the desktop.                                                                                             |
| `tidyUpWindows()`                                | Arranges the visible windows in a grid, in their left-to-right order.                                                      |
| `runWindowCommand(command)`                      | Runs a keyboard command (`osWindowShortcuts.ts`) on the focused window.                                                    |

`windows` lists every window with its `minimized` state, and `focusedWindow` is the top window that is not minimized.

**The URL follows focus.**
When the focused window changes, or the focused window navigates, the page URL is replaced with that window's path, and the tab title follows the window.
The OS never pushes a history entry.
It moves the address bar without a kea-router location change, so this page never loads the window's scene: no second pageview, and a scene with its own page layout (onboarding, login) cannot replace the OS shell.
Reloading on such a URL shows that page without the OS, and the OS comes back on the next regular page.
A push or a back/forward to another path on this page (for example from the command palette) opens that path as a window, or focuses the window that shows it.
Redirects on this page (replaces) are ignored, because the window runs the same redirect.
Navigation inside a window adds entries to the browser's history, so back and forward step through the pages the windows visited, in the order they visited them.
The window that back or forward moves comes to the front, and the URL follows it.
When the last visible window closes or minimizes, the URL stays on its path.

**The layout persists per project** in `localStorage` under `posthog-os-windows:<project id>`: paths, bounds, stacking order, minimized and maximized state.
Tabs of one project share it, and the last save wins.
Loading a URL opens it as the focused window on top of the saved layout.
Each tab keeps the URL it showed last in `sessionStorage` (`posthog-os-windows-url:<project id>`).
Reloading on that URL only restores the layout, so a window closed on that URL stays closed after a reload.
A window keeps the bounds it asked for, and the desktop clamps them only for display, so a browser window that shrinks and grows back gets its layout back.
When a window navigates to another project and a reload follows, the page opens that project's desktop.
Saved paths go through `osFrameSrc` again when they load, and entries that do not parse are dropped.

**Keyboard shortcuts** use Option+Shift (Alt+Shift) and a key: arrows snap, maximize and minimize, W closes, G tidies up.
They only work while the desktop has focus, because key presses inside a window stay in its frame.

## Bridge

A framed app and the OS page talk through `postMessage` on the same origin (`bridge/osBridgeProtocol.ts`).
The framed side is `bridge/osFrameBridgeLogic`, which `Navigation` mounts in framed mode through `OsFrameBridge`.
The OS side is `bridge/osBridgeLogic`, which `OsWindowLayer` mounts.

The OS page accepts a message only when `event.origin` is its own origin and `event.source` is the `contentWindow` of an OS window frame.
The window id comes from that frame, never from the message.
`parseOsBridgeMessage` checks every field, and a message with another `channel` or `version` is dropped.
Bump `OS_BRIDGE_VERSION` for any change that a reader of the old version would get wrong.

| Message          | Sent when                                                                                                                                   | The OS page                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `location`       | The frame's path or title changes. `traversed` marks a browser back/forward.                                                                | Calls `windowNavigated`, and focuses the window after a traversal.           |
| `focus`          | A pointer goes down in the frame.                                                                                                           | Brings the window to the front.                                              |
| `open-window`    | Cmd/Ctrl+click, middle click, an in-app `target="_blank"` link, or `newInternalTab`.                                                        | Opens the path in a new window (`openWindow(path, { newWindow: true })`).    |
| `window-command` | A window shortcut (`osWindowCommandFor`) while the frame has keyboard focus.                                                                | Focuses the sender, then runs `runWindowCommand`.                            |
| `side-panel`     | The app calls `openSidePanel` for a tab that a page shows.                                                                                  | Emits `sidePanelRequested`, then opens the matching app (`osSidePanelPath`). |
| `spotlight`      | Cmd+K in the frame.                                                                                                                         | Opens the spotlight without a second `command menu opened` event.            |
| `user-changed`   | The app saved a change to the user, such as the theme.                                                                                      | Reloads its own user and sends `user-changed` to the other frames.           |
| `open-top`       | A page that refuses framing: a server page (`/api/`, `/login`, `/logout`, `/signup`, `/admin/`, `/complete/`, `/oauth/`) or another origin. | Loads the http(s) URL in the whole browser tab.                              |

The OS page sends one message to its frames, `user-changed`, after it saves a change to the user, such as the theme in the menu bar.
A frame accepts it only when `event.source` is its parent and `event.origin` is its own origin, and then reloads the user, so the new theme reaches every open window without a reload.

Links:

- A plain click on an in-app link stays in the same window, also when the link goes to another app.
- A plain click on a link to another site opens a browser tab. A link with its own `target` or a modifier keeps the browser behavior.
- A redirect in code or a form post to a page that refuses framing is caught with the Navigation API `navigate` event and goes to `open-top`. Browsers without the Navigation API load those pages in the window, which then stays blank.
- The browser's own "Open link in new tab" menu item still opens a browser tab.
- A link to `/api/` stays with the browser: a file downloads, and an OAuth start leaves the window through `open-top`.
  A redirect in code to any `/api/` URL without `download` leaves the window too, so an inline API response replaces the desktop until the person goes back. The layout is saved, so the windows come back.
- `newInternalTab` opens a new window both inside a window and on the OS page itself (for example "New SQL query" in the spotlight).
- On the desktop, Cmd/Ctrl+click or a middle click on an icon opens another window, also when a window already shows that app.

Side panels: PostHog AI, activity, notebooks and exports open as apps in windows.
Support opens its form as a modal inside the window.
Discussions, access control and the info panel have no page yet. The window shows a toast that the panel is not available in windows yet, and sends nothing to the OS.

Toasts, modals and popovers render inside the frame that opened them, so they stay inside its window.

A frame on another origin (an OAuth provider, billing) cannot send messages.
When the person clicks into one, the OS page loses focus to it, and `osBridgeLogic` brings that window to the front.
Same-origin frames do not use this, because an app that focuses an input on load would otherwise raise its window.

## Spotlight

`spotlight/OsSpotlight` replaces the app's `Command` menu on the OS page and uses the same search (`Search`) and open state (`commandLogic`).
Cmd+K on the desktop, or inside a window, opens it.
The menu bar search icon opens it with `osSpotlightLogic.actions.openSpotlight()`.
A result opens in a window, or focuses the window that shows it. Cmd/Ctrl+Enter opens another window, and a result on another site opens a browser tab.
