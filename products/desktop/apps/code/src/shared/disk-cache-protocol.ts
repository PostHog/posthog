export const DISK_CACHE_SCHEME = "posthog-cache";

const CACHED_IMAGE_ORIGIN = `${DISK_CACHE_SCHEME}://images/`;

export function isCacheableImageUrl(remoteUrl: string): boolean {
  try {
    return new URL(remoteUrl).protocol === "https:";
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
