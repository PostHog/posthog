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
| `dock/`      | The dock                                                                    | See "Dock and App Store" below.                                     |
| `store/`     | App Store and the installed-apps list                                       | See "Dock and App Store" below.                                     |
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

The OS page sends two messages to its frames:

- `user-changed`, after it saves a change to the user, such as the theme in the menu bar. The frame reloads the user, so the new theme reaches every open window without a reload.
- `navigate`, with a path on this origin, when the person picks a page in the menu bar's app menu. The frame pushes the path to its router, so the page changes without a reload. `osBridgeLogic.actions.navigateWindow(id, path)` sends it. A frame on another origin cannot read it, so that frame loads the path again. A frame whose app is still loading drops it, so when the frame's next `location` report shows another page, the OS page sends it once more.

A frame accepts them only when `event.source` is its parent and `event.origin` is its own origin.
`parseOsHostMessage` drops a `navigate` whose path does not start with a single `/`.

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

## Menu bar

`shell/OsMenuBar` has three parts: the PostHog menu and the app menu on the left, the search field in the middle, and the project, PostHog AI, notifications and account on the right.
The PostHog menu holds Home, App Store, Choose desktop apps, Settings and About PostHog. There is no list of apps, because the desktop and the App Store show them.

**The app menu** (`shell/OsAppMenu`, `shell/osMenuBarLogic`) shows the name of the app in the focused window, and a menu of that app's pages.
With no focused window, it does not render.
`shell/osAppMenus.ts` finds the app for the window's path:

- `OS_APP_MENU_PAGES` lists the pages of the apps that have tabs, with the labels and the order of those tabs. Tabs behind a feature flag stay out.
- An app claims its own link and every page it lists, and the longest match wins, the same as the dock (`osAppForPath`). Only apps the user can see claim pages.
- An app without listed pages gets its home page.
- "New" lists the product manifests' new items (`getTreeItemsNew`) that open one of the app's scenes, without the ones behind a feature flag that is off.
- A page that another app owns is a related app (Dashboards under Product analytics). It opens in its own window. A "new" item that another app owns is left out. So a page picked in the menu never moves the window to another app.
- A page listed with a `flag` shows only while that feature flag is on, the same as the app's tab. The first page of an app is the tab it opens on, and a URL without the tab key marks that page.

The page the window shows is highlighted, and screen readers hear "current page". Picking a page shows it in the focused window through the bridge's `navigate` message.
The menu also opens the app in a new window, and minimizes or closes the focused window.
A window that no app claims, such as a person, gets its title and only the window items.
The menu closes when another window comes to the front, or when the person clicks into a window.

**The desktop** draws every icon in white, except the App Store, which is drawn in the accent color (`highlighted` in `osDesktopApps`).

## Spotlight

`spotlight/OsSpotlight` replaces the app's `Command` menu on the OS page and uses the same search (`Search`) and open state (`commandLogic`).
Cmd+K on the desktop, or inside a window, opens it.
The search field in the middle of the menu bar opens it with `osSpotlightLogic.actions.openSpotlight()`.
A result opens in a window, or focuses the window that shows it. Cmd/Ctrl+Enter opens another window, and a result on another site opens a browser tab.

## Dock and App Store

**Installed apps** are the user's `UserProductList` rows, the same list that backs the desktop icons and the sidebar's "My tools".
`store/osInstalledAppsLogic` reads it through `customProductsLogic`.
`installApp(key)` and `removeApp(key)` write it through its API, so the desktop and the sidebar follow.
While a write is in flight, the value it asks for wins over the loaded list, so a reload that answers with an older list cannot undo a click.
After the last write settles, the logic reloads the list once if a load ran during the write, and only the newest load applies.
A write that fails is undone at once, and the list reloads.
The App Store window reloads the list each time it gets focus, because Settings or another store window can change it.

**The catalog** (`store/osAppCatalog.ts`) comes from the product tree in `products.tsx`.
An app behind a feature flag that is off, or an app the user has no access to, stays out of the store, the same as in "My tools".
The front page groups released apps by the job they help with, then lists Beta and Labs (alpha and unreleased apps).
Activity, PostHog AI and Settings are not in the store, because they are always there. The dock knows them only for their icons (`OS_SYSTEM_APPS`).

**The App Store is a scene** (`Scene.OsAppStore`) at `/app-store`, with one listing per app at `/app-store/<slug>`.
It opens in a window like any other app, and with the flag off it shows the not-found page.
The store frame keeps its own copy of the installed apps, so it tells the OS page about changes with `postMessage` (`store/osStoreMessages.ts`).
It sends `installed-changed` after each write, and `open-app` with a catalog key for Open.
It never sends a URL, so a frame can only ask the OS for apps the OS already knows.
The OS page accepts these messages only from its own window frames on the same origin.

**The dock** (`dock/osDockLogic`) shows the App Store, a divider, then one item per open window in the order the windows opened.
Each item shows the icon of the app the window belongs to (`osAppForPath`), the window title as its tooltip, and a dot.
A window that no app claims, or that several apps could claim, gets a plain window icon.
The focused window is highlighted, and a minimized window is dimmed.
A click restores a minimized window, focuses a window in the background, and minimizes the focused window (`activateWindow`).
The top App Store window belongs to the App Store item, so the store is not listed twice, and the App Store item follows the same click rules.
With no window open, the dock shows only the App Store.
The dock sits below the window layer, so maximized and snapped windows stop above it.
Tiles shrink so every window keeps a tile on screen.
In the DOM the dock comes right after the menu bar, so the keyboard reaches it before the windows.
