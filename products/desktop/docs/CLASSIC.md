# Classic preview

Classic opens the PostHog web dashboard pages inside the desktop app.
Select Classic below Loops and Context in the navigation rail.
The existing collapsible column holds dashboard navigation.
The page body uses the cloud web app, not a second dashboard renderer.

This proof of concept supports US and EU cloud projects.
Sign in to the web app inside Classic with the same account as desktop.
The web sign-in is separate from desktop OAuth and can have different permissions.
External sign-in redirects and popup windows are blocked, so use an account with a direct PostHog sign-in for this preview.
Desktop does not pass its access token to the page.
The web session uses an in-memory partition per desktop account and cloud region.
It does not persist after the app closes.

Dashboard lists, dashboard pages, and insight pages use the web app.
Select Dashboards in the page header to return to the dashboard list.
Other project pages and web chat are outside this preview.
The web navigation and chat panel are hidden with host-injected CSS.
This CSS depends on web layout selectors and must be checked when the web layout changes.
A supported web layout mode should replace it before a wider release.

The remote page has no preload script, Node access, or desktop IPC bridge.
The host allows only the selected PostHog cloud origin for top-level navigation.
Web security and the browser sandbox remain enabled.
The web host does not expose Classic because it cannot provide this isolated view.

For review, check sign-in, dashboard filters, opening an insight, returning to the list, project switching, and sidebar collapse.
Check both a full-width window and a narrow content area.
The existing sidebar click event records Classic selection without dashboard content or URLs.
