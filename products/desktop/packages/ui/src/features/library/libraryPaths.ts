import type { EmbedLocation } from "./embeddedWebAppContract";

/** Library's routes are the web app's own paths under this prefix, so its links and history keep working. */
export const LIBRARY_ROOT = "/library";

/** The shell href for a web app URL such as `/project/2/insights?tab=saved`. */
export function toLibraryHref(webAppUrl: string): string {
  const url = webAppUrl.startsWith("/") ? webAppUrl : `/${webAppUrl}`;
  return `${LIBRARY_ROOT}${url}`;
}

/** The web app's location for a shell location, or null when the shell is not on a Library route. */
export function toWebAppLocation(
  shellLocation: EmbedLocation,
): EmbedLocation | null {
  const { pathname, search, hash } = shellLocation;
  if (pathname !== LIBRARY_ROOT && !pathname.startsWith(`${LIBRARY_ROOT}/`)) {
    return null;
  }
  return {
    pathname: pathname.slice(LIBRARY_ROOT.length) || "/",
    search,
    hash,
  };
}

/** The web app path of a PostHog URL such as `https://us.posthog.com/project/2/insights/abc`. */
export function webAppPathFromUrl(url: string): string {
  const { pathname, search, hash } = new URL(url);
  return `${pathname}${search}${hash}`;
}
