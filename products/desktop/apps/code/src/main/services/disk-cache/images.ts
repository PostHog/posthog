import type { DiskCacheNamespace } from "@main/services/disk-cache/service";
import { logger } from "@main/utils/logger";
import type { FetchLike } from "@posthog/core/auth/auth";
import {
  fromCachedImageUrl,
  isCacheableImageUrl,
} from "@shared/disk-cache-protocol";

const log = logger.scope("diskCache images");

export const CACHED_IMAGE_MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000;

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

/** Ceiling for the whole images namespace, well past what avatars and icons need. */
export const CACHED_IMAGE_NAMESPACE_MAX_BYTES = 100 * 1024 * 1024;

interface CachedImage {
  bytes: Uint8Array;
  contentType: string;
}

/**
 * Reads a body up to `maxBytes` and gives up as soon as the cap is passed.
 * `content-length` is only a hint here: a chunked response omits it, so a
 * server could otherwise stream forever into the main process.
 */
async function readCapped(
  response: Response,
  maxBytes: number,
): Promise<Uint8Array | null> {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) return null;

  if (!response.body) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    return bytes.byteLength > maxBytes ? null : bytes;
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel("image too large").catch(() => {});
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
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
      // The network stack follows redirects for us, so check where the bytes
      // came from: a public host can bounce the request onto an intranet
      // address or downgrade it to http.
      const finalUrl = response.url || remoteUrl;
      if (finalUrl !== remoteUrl && !isCacheableImageUrl(finalUrl)) {
        log.warn("Image redirected off-limits", { remoteUrl, finalUrl });
        return stale;
      }
      const contentType = response.headers.get("content-type") ?? "";
      // Media types are case-insensitive (RFC 9110), so a valid header like
      // "Image/PNG" must pass. Normalize for the check; store the original.
      if (!contentType.trim().toLowerCase().startsWith("image/")) return stale;

      const bytes = await readCapped(response, MAX_IMAGE_BYTES);
      if (!bytes) {
        log.warn("Image too large", { remoteUrl, max: MAX_IMAGE_BYTES });
        return stale;
      }

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
