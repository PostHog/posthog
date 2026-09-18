# Library and Tools preview

Library and Tools open existing PostHog web pages inside Desktop or its browser host.
They replace the Classic rail item, below Loops and Context.
Old `/classic` links redirect to `/library`.

## Library

Library lists saved objects registered with the web file system, including insights, dashboards, feature flags, experiments, notebooks, surveys, and cohorts.
It uses the existing file system index and access checks, not a second object store.
Objects that have not yet been indexed are imported through the web app's existing unfiled endpoint.
Search, object type, sort order, and pagination use the server.
The URL stores these filters, so browser back and forward can restore a list.

Select an object to open its existing web detail page, including its tabs, editing controls, and normal panels.
Select a type and **Open product view** to use the existing product list and its creation controls.
Select **All objects** in the collapsible sidebar to return to the library.
Objects without a supported project page are shown but cannot be opened in this preview.
The library covers the web file system's registered objects, not every database row or raw event.

## Tools

Tools lists working pages from the web product and data registries.
This includes SQL editor, analytics, data pipeline sources and destinations, and data management pages.
Search and category filters narrow the list.
Registered saved-object lists belong in Library; other working pages belong in Tools.
The registry retains each tool's feature flag and access checks.
New products can use the same registries and existing routes without a separate Desktop page.

## Shared layout and isolation

The web app owns the collapsible navigation beside the Desktop rail, the product tabs, and the page body.
Library and Tools use compact sidebar rows that match Desktop: 28 px high, with 13 px labels and 16 px icons.
Desktop does not add a second sidebar for these destinations.
Desktop's native project picker is authoritative.
Selecting a different project reloads the frame for that project and account.
The web project and account pickers, Browse toggle, and chat are hidden.
Normal web pages outside an embed keep their existing layout.

The transport retains the `__desktop_classic=1` and `__desktop_parent_origin` parameters for compatibility.
`__desktop_section=library` or `__desktop_section=tools` selects the navigation and landing page.
The embed preserves these parameters with browser history updates, without dispatching a second router action.

The Electron host supports US and EU cloud projects through an isolated webview.
The remote page has no preload script, Node access, or desktop IPC bridge.
Web security and the browser sandbox stay enabled.
External popups, organization-level document routes, and chat routes are not supported.

The browser host uses a sandboxed iframe and the browser's web session, not the Desktop OAuth token.
The frame stays hidden until its expected origin and window confirm the same account and project.
No dashboard content or access token crosses this message channel.
Sign in to PostHog in a separate browser tab with the same account if needed, then select **Reload** after a load failure.
Browser privacy settings can block cross-site session cookies; use a same-site deployment for this preview.

The CSP exception applies only to supported project document routes with `__desktop_classic=1`.
Local development and `*.dev.posthog.dev` allow `http://localhost:5273` as a parent.
Production uses the app's own origin and existing trusted parents, never a parent supplied through the URL or localhost.
Login, chat, API, and admin policies stay unchanged.

## Local browser test

1. Run PostHog web from this branch at `http://localhost:8010` with `DEBUG` enabled.
2. From `products/desktop`, run `pnpm --filter @posthog/web dev`.
3. Open `http://localhost:5273`, select **Local development**, and sign in.
4. Select **Library**. Search and filter the list, then open a dashboard, insight, flag, experiment, or notebook.
5. Select **Tools**, search for SQL editor, and open it. Check sources and destinations through the tool navigation.
6. Check product tabs, browser back and forward, sidebar collapse, narrow layouts, and native project switching.

The local OAuth application must allow `http://localhost:5273/callback`.
See [local development](./LOCAL-DEVELOPMENT.md#mismatching-redirect-uri-during-browser-sign-in) for redirect and RSA signing-key setup, and `apps/web/README.md` for OAuth and CORS requirements.
The browser host's existing consent check can reject project-scoped development tokens before these views open.
This preview does not change that check.

A hosted test needs both the PostHog web changes and the browser host build from this PR.
Serve `apps/web/dist` on the app's origin or an existing trusted parent, and register its OAuth callback and CORS origin.
The `/code/channel/...` links open Desktop; they do not serve this browser build.
This PR does not deploy a public browser host.

The existing sidebar click event records Library and Tools selection separately, without object names or search text.
