---
name: building-the-toolbar
description: Builds, watches, checks and verifies the PostHog toolbar in both of its forms, the floating toolbar that posthog-js loads on customer pages and the browser extension that shows the toolbar in a Chrome side panel or Firefox sidebar. Use when changing anything under frontend/src/toolbar/ (floating toolbar or extension), frontend/toolbar-config.mjs, or the toolbar build and guard scripts, or when asked to build, watch, load unpacked, or test the toolbar or the toolbar extension in a browser. Covers `pnpm build:toolbar-all` and `pnpm watch:toolbar-all`, the check-toolbar-size, check-toolbar-graph and check-toolbar-csp-eval guards, why both forms must be built and kept in sync, and how to check each one in a real browser.
---

# Building the toolbar

One source tree, `frontend/src/toolbar/`, ships in two forms.
Both builds live in `frontend/toolbar-config.mjs` and share its toolbar module plugin, which swaps app modules for the toolbar's shims and keeps denylisted packages out.

| Form              | Entry                                            | Output (under `frontend/dist/`)                     | Runs in                                          |
| ----------------- | ------------------------------------------------ | --------------------------------------------------- | ------------------------------------------------ |
| Floating toolbar  | `src/toolbar/floating/index.tsx`                 | `toolbar.js` loader, `toolbar/` app chunks          | Customer pages, loaded by posthog-js             |
| Browser extension | `src/toolbar/extension/panel.tsx`, `content.tsx` | `toolbar-extension/<browser>/`, one zip per browser | Chrome side panel, Firefox sidebar (Manifest V3) |

## Where code goes

| Folder               | Holds                                                                                               |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| `toolbar/shared/`    | The kea logics, the API and auth helpers, the shims, utils, and every component both forms render   |
| `toolbar/floating/`  | The floating toolbar: its entry and loader, the bar, and the menus that bind shared logic to its UI |
| `toolbar/extension/` | The extension: the panel, the content script, the page agent, and the panel's own tool components   |

Inside `floating/` and `extension/`, only the entry points the build names sit at the top. Everything else goes in a folder:

| Folder                  | Holds                                                                                                                       |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `components/<feature>/` | React components, their stories and tests. The feature folders use the names `shared/` uses, such as `flags`                |
| `logics/`               | The form's kea logics and the pure helpers they test. The extension splits them into `panel/` and `page/` by where they run |
| `messaging/`            | Extension only: the port, page agent and form sync protocol between the panel, the content script and the page              |
| `browser/`              | Extension only: the wrappers around the extension APIs                                                                      |

- Put logic in `shared/`. A form folder configures shared code for its form: it mounts logics, binds them to its UI, and renders shared components with its own data.
- When a component is the same in both forms, it lives in `shared/` and takes its data and callbacks as props. `WebExperimentVariant` is the pattern: `floating/components/experiments/ExperimentsTabEditorProvider.tsx` and `extension/components/experiments/ExtensionExperimentEditorProvider.tsx` each bind it to their own state.
- `shared/` never imports from `floating/` or `extension/`, and the two forms never import each other. `toolbar/toolbarLayout.test.ts` fails on such an import.
- Keep each kea logic's `path([...])` as it is when you move its file. The path is the logic's identity and storage key, not its location.

## Build both, every time

The extension's content script, `extension/content.tsx`, runs the shared kea logics and components on the page, such as `toolbarConfigLogic`, `elementsLogic` and `ElementOverlays`.
The panel imports shared modules too, and both go through the same module plugin.
So any change under `toolbar/shared/`, or in `toolbar-config.mjs`, can break either form, even when you only meant to touch one.

- Build and check both forms for every toolbar change.
- Fix shared toolbar code in the general way.
  Do not add an extension-only branch to shared code when a fix that serves both forms exists.
  When a branch is unavoidable, keep it in one place and say why in a comment.

From `frontend/`:

```sh
pnpm build:toolbar-all    # production floating toolbar, then the extension
pnpm watch:toolbar-all    # rebuild both on change
```

To build one form only:

| Form              | Build                          | Watch                          |
| ----------------- | ------------------------------ | ------------------------------ |
| Floating toolbar  | `pnpm build:toolbar-floating`  | `pnpm watch:toolbar-floating`  |
| Browser extension | `pnpm build:toolbar-extension` | `pnpm watch:toolbar-extension` |

The dev stack (`hogli start`) already runs `pnpm watch:toolbar-floating` through `start-vite`.
While it runs, start `pnpm watch:toolbar-extension` alone, so two watchers don't write the same files.

## Run the guards

The guards read `toolbar-esbuild-meta.json` and `dist/toolbar*`, which the floating toolbar build writes.
CI runs them on a production build, so run them after `pnpm build:toolbar-all`, not after a watch build:

```sh
pnpm check-toolbar-size      # loader size, eager-set budget, every file under the CloudFront gzip limit
pnpm check-toolbar-graph     # no new toolbar-to-app import edges, no denylisted packages
pnpm check-toolbar-csp-eval  # no eval, new Function or string timers in shipped code
```

Each script's header comment explains its limits.
When `check-toolbar-graph` fails, cut the new import rather than add it to `bin/toolbar-graph-baseline.json`.

These guards cover the floating toolbar bundle only.
The extension has no guard script, but Manifest V3 refuses `eval` and remote scripts, so a break there shows when you load the extension.

Also run the toolbar tests and the logic types:

```sh
pnpm exec jest src/toolbar
pnpm typegen:write   # then check that git diff shows no drift in logic types
```

## Check it in a real browser

Tests and builds don't show a broken overlay, a missing style, or a CSP refusal. Load the build.

- **Extension.** Load `dist/toolbar-extension/chrome` unpacked in Chrome and `dist/toolbar-extension/firefox` as a temporary add-on in Firefox.
  The steps are in [the extension README](../../../frontend/src/toolbar/extension/README.md#build-and-install); read it before you load the extension the first time.
  After a rebuild, reload the extension, then close and open the panel.
  Check both browsers when you change the extension, and walk the README's [manual checks](../../../frontend/src/toolbar/extension/README.md#check-the-flows-by-hand) for the tools you touched.
- **Floating toolbar.** Start the dev stack (see `/run-posthog`), open the Toolbar page at `http://localhost:8010/toolbar`, add a test site that loads posthog-js to the authorized URLs, and launch the toolbar on it.
  `Toolbar.stories.tsx` renders the floating toolbar in Storybook when you only need to look at a component.

Check the forms you didn't mean to change as well.
A change to a shared logic shows up in both.
