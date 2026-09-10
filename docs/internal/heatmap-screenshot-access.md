# Heatmap screenshot access

Project admins can approve exact hostnames and generate a reusable cookie value for bot-protection rules on public pages.
Screenshot cookies do not authenticate users or provide access to signed-in pages.

## API contract

The canonical settings endpoint is `/api/projects/{team_id}/heatmap_screenshot/settings/`.
The `/api/environments/{team_id}/` prefix is a compatibility alias.

| Operation                                                                                             | Access                                             | Behavior                                                                                                              |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `GET settings/`                                                                                       | Project member; `project:read` for scoped API keys | Returns `allowed_hostnames`, `has_secret`, and `cookie_delivery_enabled`. Never returns the secret.                   |
| `PATCH settings/`                                                                                     | Project admin; `project:write` for scoped API keys | Replaces `allowed_hostnames` when supplied. An empty body leaves configuration unchanged. `[]` removes all approvals. |
| `PATCH /api/projects/{team_id}/rotate_heatmaps_screenshot_secret/`                                    | Project admin                                      | Generates a new secret and returns the project response. No request body.                                             |
| `PATCH /api/organizations/{organization_id}/projects/{project_id}/rotate_heatmaps_screenshot_secret/` | Project admin                                      | Equivalent organization/project route used by the generated frontend client.                                          |

The project/environment response field `heatmaps_screenshot_secret` returns a value only to project admins; other members receive `null`.
Hostname updates and rotations record activity with credential values redacted.
Concurrent rotations lock the configuration row before reading the previous value and constructing the audit change.

Hostnames are normalized to lowercase ASCII using IDNA and deduplicated. Each request accepts at most 100 hostnames.
URLs, ports, wildcards, IP addresses, and single-label names are rejected.
Approving `www.example.com` does not approve `example.com`, sibling hosts, or child hosts.
Toolbar URLs are suggestions, not approvals; changing `app_urls` never changes the approved list.

## Cookie delivery

Delivery requires all of the following:

- The installation has enabled `HEATMAP_BROWSERLESS_SCREENSHOT_COOKIES_ENABLED`.
- The project has a secret and approved hostnames.
- The starting screenshot URL uses HTTPS and its exact hostname is approved.

Eligible captures preload host-only `__ph_heatmap_render` cookies for the approved hosts, with `Secure`, `HttpOnly`, and `SameSite=Lax`.
An approved HTTPS redirect destination can receive its cookie when the starting URL is also eligible.
A capture starting on HTTP or an unapproved host receives no cookies, even if it later redirects to an approved host.
This prevents an unapproved starting page from initiating a render with project credentials.

Each width reloads configuration, so later requests respect secret rotation and removed approvals.
An in-flight request can finish with the configuration it already received.
Screenshots without eligible cookie delivery still run; live iframe previews never send the cookie.

## Settings workflow

Under **Project settings > Heatmaps > Screenshot request cookie**, admins save approved hostnames, then generate and copy the cookie value.
Configure the bot-protection exception to match the exact hostname and cookie value, keeping authentication and unrelated security rules enabled.
Rotation changes future screenshots. Remove the old value from the bot-protection rule to revoke it; rotating in PostHog does not revoke that rule.
Members see setup status without seeing the secret. Credential snippets are excluded from autocapture and session replay.

## Deployment requirements

`HEATMAP_BROWSERLESS_SCREENSHOT_COOKIES_ENABLED` defaults to `false` in both web and screenshot workers.
Keep it disabled until the renderer and all proxies have verified credential-safe logging and network isolation.
The settings API exposes the switch as `cookie_delivery_enabled`; the UI explains when delivery is disabled.

Browserless v2.51.2 logs the screenshot request body at info level, including cookie values.
The repository's dev and hobby containers set `LOG_LEVEL=warn` and `DEBUG=-*` to suppress this logging.
For separately managed renderers, apply equivalent filtering or cookie-value redaction before enabling delivery.
See the [Browserless logging configuration](https://docs.browserless.io/enterprise/docker/config#logging--debugging) and the [pinned screenshot handler](https://github.com/browserless/browserless/blob/v2.51.2/src/shared/screenshot.http.ts#L94).

Before setting the switch to `true`:

1. Restart the renderer with safe logging and verify successful and failing synthetic requests do not leave cookie values in renderer or proxy logs.
2. Verify fresh browser contexts, host-only cookie isolation, and outbound network restrictions on the deployed renderer.
3. Drain older screenshot workers, then enable the switch consistently on the web and worker processes.

Use invented cookie values and reserved example domains for these checks.
No existing project configuration receives automatic hostname approvals.
