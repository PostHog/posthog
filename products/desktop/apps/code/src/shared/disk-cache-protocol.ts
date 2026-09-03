import { isPrivateHostname } from "@posthog/core/local-mcp/localMcpImport";

export const DISK_CACHE_SCHEME = "posthog-cache";

const CACHED_IMAGE_ORIGIN = `${DISK_CACHE_SCHEME}://images/`;

/**
 * The scheme is registered on the session that also renders untrusted artifact
 * HTML, so any preview can name a source and make the main process fetch it.
 * Public https only: an intranet address would let the preview reach hosts its
 * own sandbox cannot, and embedded credentials would have the main process
 * present them to a host the preview chose.
 */
export function isCacheableImageUrl(remoteUrl: string): boolean {
  try {
    const url = new URL(remoteUrl);
    if (url.username || url.password) return false;
    return url.protocol === "https:" && !isPrivateHostname(url.hostname);
  } catch {
    return false;
  }
}

export function toCachedImageUrl(remoteUrl: string): string {
  return `${CACHED_IMAGE_ORIGIN}?src=${encodeURIComponent(remoteUrl)}`;
}

export function fromCachedImageUrl(protocolUrl: string): string | null {
  try {
    const url = new URL(protocolUrl);
    if (url.protocol !== `${DISK_CACHE_SCHEME}:` || url.host !== "images") {
      return null;
    }
    const remoteUrl = url.searchParams.get("src");
    return remoteUrl && isCacheableImageUrl(remoteUrl) ? remoteUrl : null;
  } catch {
    return null;
  }
}
