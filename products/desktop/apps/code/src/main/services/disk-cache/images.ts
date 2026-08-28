import type { DiskCacheNamespace } from "@main/services/disk-cache/service";
import { logger } from "@main/utils/logger";
import type { FetchLike } from "@posthog/core/auth/auth";
import { fromCachedImageUrl } from "@shared/disk-cache-protocol";

const log = logger.scope("diskCache images");

export const CACHED_IMAGE_MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000;

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

interface CachedImage {
  bytes: Uint8Array;
  contentType: string;
}

export function createCachedImageHandler(
  images: DiskCacheNamespace,
  fetch: FetchLike,
  maxAgeMs: number = CACHED_IMAGE_MAX_AGE_MS,
): (request: Request) => Promise<Response> {
  const inFlight = new Map<string, Promise<CachedImage | null>>();

  async function refresh(
    remoteUrl: string,
    stale: CachedImage | null,
  ): Promise<CachedImage | null> {
    try {
      const response = await fetch(remoteUrl);
      if (response.status === 404) {
        await images.delete(remoteUrl);
        return null;
      }
      if (!response.ok) {
        log.warn("Image fetch failed", { remoteUrl, status: response.status });
        return stale;
      }
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.startsWith("image/")) return stale;

      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.byteLength > MAX_IMAGE_BYTES) return stale;

      await images.set(remoteUrl, bytes, contentType);
      return { bytes, contentType };
    } catch (error) {
      log.warn("Image fetch threw", { remoteUrl, error });
      return stale;
    }
  }

  async function resolve(remoteUrl: string): Promise<CachedImage | null> {
    const cached = await images.get(remoteUrl, { maxAgeMs });
    if (cached && !cached.stale) return cached;

    const pending = inFlight.get(remoteUrl);
    if (pending) return pending;

    const refreshed = refresh(remoteUrl, cached).finally(() => {
      inFlight.delete(remoteUrl);
    });
    inFlight.set(remoteUrl, refreshed);
    return refreshed;
  }

  return async (request) => {
    const remoteUrl = fromCachedImageUrl(request.url);
    if (!remoteUrl) return new Response(null, { status: 400 });

    const image = await resolve(remoteUrl);
    if (!image) return new Response(null, { status: 404 });

    return new Response(image.bytes as BodyInit, {
      headers: {
        "Content-Type": image.contentType,
        "Cache-Control": `max-age=${Math.floor(maxAgeMs / 1000)}`,
      },
    });
  };
}
