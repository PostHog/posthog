# Toolbar browser extension

The extension gives the toolbar tools to a page without the floating toolbar.
It opens from the extension button as a side panel in Chrome and as a sidebar in Firefox, and shows `panel.html`.
The panel follows the active tab of its window.

## Build and install

Build both browser folders from `frontend/`:

```sh
pnpm build:toolbar-extension        # one build
pnpm watch:toolbar-extension        # rebuild on change
```

The build writes `dist/toolbar-extension/chrome/` and `dist/toolbar-extension/firefox/`.
Only `manifest.json` is different between them.
It also zips each folder into `dist/toolbar-extension/posthog-toolbar-<browser>-<version>.zip`.

A pull request that changes the extension runs the "Toolbar extension" workflow.
Download the `toolbar-extension` artifact from the run to install that build without building it yourself.

### Chrome (116 or later)

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and select `frontend/dist/toolbar-extension/chrome`, or the unzipped Chrome folder from the artifact.
3. Pin the extension, then click its button to open the side panel.

After a rebuild, click the reload icon on the extension card, then close and open the side panel.

### Firefox (128 or later)

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on** and select `frontend/dist/toolbar-extension/firefox/manifest.json`, or the Firefox zip from the artifact.
3. Click the extension button to open the sidebar.

Firefox removes a temporary add-on when it quits.
A permanent install needs an add-on signed by addons.mozilla.org.

## Permissions

| Permission                  | Why                                                                                                                                                                                                  |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `http://*/*`, `https://*/*` | The side panel reads the URL of the active tab and runs scripts in it when the user switches tabs. The same grant calls the PostHog API with your PostHog login, on Cloud and on a self-hosted host. |
| `scripting`                 | Injects the content script, and reads the page's posthog-js settings in the page's world.                                                                                                            |
| `storage`                   | Saves the PostHog host and the toolbar's OAuth tokens for each project.                                                                                                                              |
| `sidePanel` (Chrome)        | Shows the side panel.                                                                                                                                                                                |

The manifest also lists `content.css` and its fonts in `web_accessible_resources`, because the content script links them into its shadow root on the page.

### Site access

Both browsers let the user take site access back from an extension.
When the extension can't reach the PostHog host, the panel asks for access to it.
When it can't reach the site, the panel asks the user to reload the page and try again.

## How the page tools work

The page tools run the floating toolbar's own logics in the content script, and draw its overlays in the content script's shadow root:

- `elementsLogic` for Inspect.
- `heatmapToolbarMenuLogic`, `heatmapDataLogic` and `heatmapCaptureLogic` for the heatmap.
- `actionsLogic` and `actionsTabLogic` for actions.
- `flagsToolbarLogic` for feature flags.
- `eventDebugMenuLogic` for the event debugger, and `webVitalsToolbarLogic` for web vitals.
- `screenshotUploadLogic` for screenshots for events.
- `experimentsLogic` and `experimentsTabLogic` for web experiments. The page previews a variant by changing its own DOM, and goes back to its original state when the user leaves the experiment, saves it, or closes the tool.
  The panel shows their controls and gets their state through a port.

```mermaid
flowchart LR
    panel[Side panel] -- commands --> port((port))
    port -- state, tokens --> panel
    port --- content[Content script]
    content -- toolbarConfigLogic with the extension's tokens --> logics[Toolbar logics]
    logics -- bearer token --> api[PostHog API]
    logics -- overlays --> page[(Page)]
```

- **Sign-in.** The panel calls PostHog with the PostHog session cookie for the checks it runs before the page tools.
  A session cookie sent from an extension page fails Django's CSRF origin check on writes, so the page tools use the toolbar's OAuth flow instead.
  When the panel first shows the tools for a project, it opens `/toolbar_oauth/authorize/` in a background tab with the page as the redirect.
  It reads the code from that tab's URL hash, closes the tab, and exchanges the code with its own PKCE verifier.
  The tokens are stored per PostHog host and project.
  If that fails, or the tokens expire again, the panel shows **Connect**, which runs the same flow in a tab the user can see.
- **Refresh.** The content script refreshes the tokens on a 401 like the floating toolbar does, and sends the new tokens to the panel to store.
- **Storage.** In extension mode `toolbarConfigLogic` doesn't read the page's URL hash or write the page's `localStorage`, so it leaves the floating toolbar's session on the page alone.
- **posthog-js.** The content script can't reach the page's `window.posthog`.
  The panel reads the version, the scroll-depth setting, the heatmap setting and the flag state in the page's world, and passes them on.
  For flag overrides the panel also injects `page-agent.js` into the page's world.
  The content script sends it requests through `window.postMessage`, and the page agent calls posthog-js and reports the flag state back.
  The page agent also forwards each event posthog-js captures, for the event debugger and the web vitals of the page load, and reads the debug info.
- **Event debugger.** The page keeps up to 5,000 events, like the floating toolbar.
  Each state message carries only the newest 200 rows the filters show, and the properties of the open event.
  **Export** downloads every filtered event from the page.
  When a page loads posthog-js after the panel connected, the panel checks again for a few seconds and reconnects.
- **Action form.** The panel edits its own copy of the action form, so typing doesn't wait for the page, and sends the form to the page.
  It takes the page's copy only when the page changes the form itself, for example when the user picks an element for a step.
  The page counts the matches of the selectors the form shows.
- **Injection.** The panel injects the content script on first use. The script answers a ping, so the panel doesn't inject it twice.
- **Navigation.** The panel opens a new port when the tab loads a page or the user switches tabs, and turns the mode the user picked back on.
  The page tools turn off when the last panel disconnects.

## Check the flows by hand

Use a site in the project's authorized URLs. Do these steps in Chrome and in Firefox.

1. Open the panel on the site. The panel connects the toolbar to the project: a tab opens and closes by itself.
2. Click the Inspect icon and hover an element. The panel shows its selector and actions. Click the element to keep it selected.
3. Click **Heatmap**. Check the clickmap counts, the heatmap canvas, the scroll depth type, **Filter to area**, **Load all**, and **Save to PostHog**.
4. Reload the page. The heatmap comes back.
5. In Inspect, select an element and click **Create action from this element**. Name the action, check the match count, and save it.
6. Click **Actions**, open an action, add an element with **Select element**, and save. Delete the action you created.
7. Click **Flags**. Turn a flag on, pick a variant, save a payload, and turn a multivariate flag off. The page reacts to each change. Click **Clear overrides**.
8. Open a page that doesn't load posthog-js as `window.posthog`. **Flags** says that it can't override flags there.
9. Switch to a tab with another site, then back. The panel shows the state of each tab.
10. Switch the project in the panel. The panel connects the toolbar to the new project.
11. Click **Events** and use the page. The events stream in. Open one, search, pause and resume, and export them.
12. Click **Web vitals**. The project's P90 metrics show, and the page load's metrics fill in as posthog-js reports them.
13. Click **More**. Check the debug info, open the current session recording, turn on **Hide PII on this page**, and add a screenshot to an event.
14. Click **Experiments** and open an experiment. Open a variant: the page shows it. Edit its HTML: the page changes as you type. Go back: the page shows its original state.
15. Create an experiment, pick an element for a transformation with **Select element**, edit it, and save it. Open a page whose snippet sets `disable_web_experiments`: **Experiments** shows a warning.
16. Switch the browser to dark mode. The panel follows it.
