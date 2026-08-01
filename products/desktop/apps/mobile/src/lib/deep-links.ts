/**
 * Deep-link URL construction for the mobile app.
 *
 * Path shape mirrors the desktop app (apps/code/src/shared/deeplink.ts and
 * the registered handlers in main/services/*-link/) so a single URL can route
 * to either client:
 *   posthog://task/<taskId>
 *   posthog://task/<taskId>/run/<runId>
 *   posthog://inbox/<reportId>
 *   posthog://inbox/<reportId>/<slug>   (slug is cosmetic, ignored on receive)
 *
 * Mobile uses the `posthog://` custom scheme (registered in app.json) and
 * https://code.posthog.com as the universal-link host. Both share the same
 * path shape, so a `code.posthog.com/task/X` URL opens the same screen as
 * `posthog://task/X`.
 *
 * For in-app navigation, prefer the `paths.*` helpers — they return the
 * router-relative path that `router.push()` expects. For external/shareable
 * links (push notifications, Slack messages, copy-link buttons), use
 * `universalUrl()` or `customSchemeUrl()`. To produce a human-readable share
 * link for an inbox report, use `inboxReportShareUrl(reportId, title)`.
 */

export const MOBILE_SCHEME = "posthog";
export const UNIVERSAL_LINK_HOST = "code.posthog.com";
export const UNIVERSAL_LINK_PREFIX = `https://${UNIVERSAL_LINK_HOST}`;

/**
 * Router-relative paths used inside the app with `router.push()` /
 * `router.replace()`. These are also the path shape that expo-router maps
 * incoming deep links to.
 */
export const paths = {
  tasksTab: "/(tabs)/tasks" as const,
  inboxTab: "/(tabs)/inbox" as const,
  automationsTab: "/(tabs)/automations" as const,
  settings: "/settings" as const,
  newTask: "/task" as const,
  task: (taskId: string) => `/task/${taskId}` as const,
  inboxReport: (reportId: string) => `/inbox/${reportId}` as const,
  automation: (automationId: string) => `/automation/${automationId}` as const,
  newAutomation: "/automation/create" as const,
  automationTemplates: "/automation" as const,
} as const;

/** A path is the part after the host: starts with `/`, no scheme. */
type AppPath = string;

/** Build a shareable `posthog://...` URL for an in-app path. */
export function customSchemeUrl(path: AppPath): string {
  const trimmed = path.replace(/^\/+/, "");
  return `${MOBILE_SCHEME}://${trimmed}`;
}

/** Build a shareable `https://code.posthog.com/...` URL for an in-app path. */
export function universalUrl(path: AppPath): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${UNIVERSAL_LINK_PREFIX}${normalized}`;
}

/**
 * Slugify a free-form title for use as a trailing path segment on a shareable
 * deep link. Mirrors `buildInboxDeeplink`'s slug rules in the desktop app
 * (apps/code/src/shared/deeplink.ts) exactly:
 *
 * - Accented Latin letters are folded to their ASCII base (`café` → `cafe`)
 *   via NFD decomposition + combining-mark stripping.
 * - Letters, digits, and the URL-unreserved punctuation `_ . ~` are kept
 *   verbatim (case preserved).
 * - Any run of other characters collapses to a single `-`, except runs that
 *   mix a colon with other unsafe chars collapse to `--`. This preserves the
 *   title-like break in `fix(inbox): Add foo` → `fix-inbox--Add-foo` while
 *   keeping standalone colons compact (`feat:bar` → `feat-bar`) and unrelated
 *   runs single (`Cost $5, 50% off` → `Cost-5-50-off`).
 * - Leading and trailing hyphens are stripped.
 *
 * Returns the empty string when the input is null/undefined/empty or
 * slugifies to nothing.
 */
export function slugifyTitle(title: string | null | undefined): string {
  if (!title) return "";
  return title
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-zA-Z0-9_.~]+/g, (run) =>
      run.includes(":") && /[^:]/.test(run) ? "--" : "-",
    )
    .replace(/^-+|-+$/g, "");
}

/**
 * Build a shareable `posthog://inbox/<reportId>` URL, optionally with a
 * cosmetic slug suffix derived from the title. The slug is purely cosmetic;
 * receivers must ignore everything after the UUID. See
 * `externalUrlToAppPath` for the corresponding inbound tolerance.
 */
export function inboxReportShareUrl(
  reportId: string,
  title?: string | null,
): string {
  const slug = slugifyTitle(title);
  const path = slug ? `/inbox/${reportId}/${slug}` : `/inbox/${reportId}`;
  return customSchemeUrl(path);
}

/**
 * Convert an incoming external URL (custom scheme or universal link) to the
 * router-relative path expo-router uses. Returns null if the URL doesn't
 * belong to us.
 *
 * A `posthog://inbox/<id>/<slug>` link (or the universal-link equivalent) is
 * normalized to `/inbox/<id>` — the slug is decorative and the route only
 * cares about the UUID. Mirrors the desktop receiver, which also ignores the
 * slug.
 *
 * Used by the auth gate to round-trip the originally-requested URL through
 * the sign-in flow.
 */
export function externalUrlToAppPath(url: string): AppPath | null {
  try {
    const parsed = new URL(url);

    let path: AppPath | null = null;
    if (parsed.protocol === `${MOBILE_SCHEME}:`) {
      // posthog://task/abc → /task/abc
      const host = parsed.hostname;
      if (!host) return null;
      const rest = parsed.pathname || "";
      const search = parsed.search || "";
      path = `/${host}${rest}${search}`;
    } else if (
      (parsed.protocol === "https:" || parsed.protocol === "http:") &&
      parsed.hostname === UNIVERSAL_LINK_HOST
    ) {
      // https://code.posthog.com/task/abc → /task/abc
      const pathname = parsed.pathname || "/";
      path = `${pathname}${parsed.search || ""}`;
    }

    if (path === null) return null;
    return stripInboxSlugSuffix(path);
  } catch {
    return null;
  }
}

/**
 * Collapse `/inbox/<id>/<slug>[?query]` to `/inbox/<id>[?query]`. No-op for
 * any path that isn't an inbox-report deep link with a trailing segment.
 */
function stripInboxSlugSuffix(path: AppPath): AppPath {
  const queryStart = path.indexOf("?");
  const pathOnly = queryStart === -1 ? path : path.slice(0, queryStart);
  const query = queryStart === -1 ? "" : path.slice(queryStart);
  const segments = pathOnly.split("/").filter(Boolean);
  if (segments.length >= 3 && segments[0] === "inbox") {
    return `/inbox/${segments[1]}${query}`;
  }
  return path;
}
