# Classic preview

Classic opens the PostHog web app inside the desktop app or its browser host.
Select Classic below Loops and Context in the navigation rail.
The web app owns the collapsible product navigation beside the rail.
Desktop does not draw a second sidebar for Classic.
One frame contains the existing web navigation, product tabs, scene layout, and page body.
Products use their existing routes and views. They do not need a Classic adapter or a separate navigation entry.

This proof of concept supports US and EU cloud projects.
Sign in to the web app inside Classic with the same account as desktop.
The web sign-in is separate from desktop OAuth and can have different permissions.
External sign-in redirects and popup windows are blocked, so use an account with a direct PostHog sign-in for this preview.
Desktop does not pass its access token to the page.
The web session uses an in-memory partition per desktop account and cloud region.
It does not persist after the app closes.

Project product pages, their tabs, settings, and normal scene panels use the web app.
Select Dashboards in the page header to return to the dashboard list.
Web chat and the nested Desktop route are outside this preview.
The shared web layout hides the Chat and Browse navigation tabs and disables the AI side panel.
The product navigation stays visible without a Browse toggle.
It keeps normal panels such as Actions, Activity logs, Access, and Discuss.
Electron uses this layout too, not injected CSS.
Both the Desktop build and the web app changes from this PR must be deployed together.
Use the web sidebar's resize handle or press `[` inside Classic to collapse its navigation.
The Desktop sidebar state stays unchanged for other destinations.
Desktop's native project picker controls Classic's project.
Classic hides the web account and project pickers, including in collapsed navigation and fullscreen views.
Selecting another project in Desktop reloads Classic for that project.
Organization-level document routes outside `/project/<id>/` and external sign-in or popup flows are not supported in this preview.

The remote page has no preload script, Node access, or desktop IPC bridge.
The host allows only the selected PostHog cloud origin for top-level navigation.
Web security and the browser sandbox remain enabled.

## Browser preview

The browser host uses a sandboxed iframe instead of an Electron webview.
It uses the browser's web session, not the Desktop OAuth token.
Select **Open web app** to sign in with the same account, then select **Reload Classic**.
The frame stays hidden until a message from the expected frame and cloud origin confirms the same account and project.
If the page cannot confirm this, Classic shows an error instead of an empty frame.
Browser privacy settings can block session cookies in cross-site frames.
Use a same-site deployment for this preview.

The web app recognizes `__desktop_classic=1` with `__desktop_parent_origin` inside a frame.
This layout keeps the full web navigation except chat, retains the parameters during navigation, and limits the body to the selected project's routes.
It keeps the host parameters in browser history without sending another router action.
Product tabs can replace their own search parameters without a loop between the product router and Classic.
Normal top-level pages keep their existing layout.
No dashboard content or access token is sent through frame messages.

The CSP change applies only to project document routes with `__desktop_classic=1`, excluding chat and nested Desktop routes.
It adds the app's own origin to the existing trusted frame parents.
Local development and `*.dev.posthog.dev` also allow the browser host at `http://localhost:5273`.
Production does not allow localhost or an origin supplied through a query parameter.
Login, chat, API, and admin policies stay unchanged.

To test both sides from this PR:

1. Run the PostHog web app from this branch at `http://localhost:8010` with `DEBUG` enabled.
2. From `products/desktop`, run `pnpm --filter @posthog/web dev`.
3. Open `http://localhost:5273`, select **Local development**, and sign in. The local OAuth application must allow `http://localhost:5273/callback`. Configure the local RSA signing key as described in `docs/LOCAL-DEVELOPMENT.md`. See `apps/web/README.md` for browser OAuth and CORS requirements.
4. Select **Classic**. If needed, select **Open web app** to establish the local web session, then reload Classic.
5. Open a dashboard, change a filter, open an insight, and use **Dashboards** to return. Open another product from the web sidebar and check its tabs and views. Open a normal scene panel. Collapse the web sidebar and check a narrow window. Switch projects in Desktop and check that the frame reloads for that project.

The browser host's existing organization-consent check can reject project-scoped development tokens before Classic opens.
This preview does not change that check.

For a hosted test, build the browser host with `pnpm --filter @posthog/web build` and serve `apps/web/dist` on the app's origin or an existing trusted parent origin.
Deploy the web app changes from this PR too, and register that host's OAuth callback and CORS origin.
The `/code/channel/...` links open Desktop; they do not serve this browser build.
This PR does not deploy a new public browser host.

For review, check sign-in, dashboard filters, product navigation, tabs, normal scene panels, project switching, and sidebar collapse.
Check both a full-width window and a narrow content area.
The existing sidebar click event records Classic selection without dashboard content or URLs.
