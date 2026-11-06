import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { FetchLike } from "@posthog/core/auth/auth";
import { toCachedImageUrl } from "@shared/disk-cache-protocol";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createCachedImageHandler } from "./images";
import { DiskCache, type DiskCacheNamespace } from "./service";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
const OLD_PNG = new Uint8Array([0x01, 0x02]);
const REMOTE = "https://example.com/a.png";
const MAX_AGE_MS = 100;

function imageResponse(bytes: Uint8Array, contentType = "image/png"): Response {
  return new Response(bytes as BodyInit, {
    headers: { "content-type": contentType },
  });
}

function request(remoteUrl: string): Request {
  return new Request(toCachedImageUrl(remoteUrl));
}

describe("createCachedImageHandler", () => {
  let rootDir: string;
  let clock: number;
  let images: DiskCacheNamespace;

  beforeEach(async () => {
    rootDir = await mkdtemp(join(tmpdir(), "disk-cache-images-"));
    clock = 1_000;
    images = new DiskCache({ rootDir, now: () => clock }).namespace("images");
  });

  afterEach(async () => {
    await rm(rootDir, { recursive: true, force: true });
  });

  async function seedStaleCopy(): Promise<void> {
    await images.set(REMOTE, OLD_PNG, "image/png");
    clock += MAX_AGE_MS + 1;
  }

  it("fetches once and serves later requests from disk", async () => {
    const fetch = vi.fn<FetchLike>(async () => imageResponse(PNG));
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const first = await handler(request(REMOTE));
    const second = await handler(request(REMOTE));

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(first.status).toBe(200);
    expect(second.headers.get("content-type")).toBe("image/png");
    expect(new Uint8Array(await second.arrayBuffer())).toEqual(PNG);
  });

  it("accepts an image whose media type is not lowercase", async () => {
    const fetch = vi.fn<FetchLike>(async () => imageResponse(PNG, "Image/PNG"));
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const response = await handler(request(REMOTE));

    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(PNG);
  });

  it("shares one fetch between concurrent requests for the same URL", async () => {
    const fetch = vi.fn<FetchLike>(async () => imageResponse(PNG));
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const responses = await Promise.all([
      handler(request(REMOTE)),
      handler(request(REMOTE)),
      handler(request(REMOTE)),
    ]);

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(responses.map((response) => response.status)).toEqual([
      200, 200, 200,
    ]);
  });

  it("refreshes a stale copy from the remote", async () => {
    await seedStaleCopy();
    const fetch = vi.fn<FetchLike>(async () => imageResponse(PNG));
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const response = await handler(request(REMOTE));

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(PNG);
  });

  it("responds 404 when the remote has no image and forgets the stale copy", async () => {
    await seedStaleCopy();
    const fetch = vi.fn<FetchLike>(
      async () => new Response(null, { status: 404 }),
    );
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const response = await handler(request(REMOTE));

    expect(response.status).toBe(404);
    expect(await images.get(REMOTE, { maxAgeMs: Infinity })).toBeNull();
  });

  it.each([
    [
      "the fetch throws",
      async (): Promise<Response> => {
        throw new Error("offline");
      },
    ],
    [
      "the remote returns 500",
      async (): Promise<Response> => new Response(null, { status: 500 }),
    ],
    [
      "the remote returns a non-image",
      async (): Promise<Response> =>
        new Response("<html>", { headers: { "content-type": "text/html" } }),
    ],
    [
      "the remote declares a length past the cap",
      async (): Promise<Response> =>
        new Response(PNG as BodyInit, {
          headers: {
            "content-type": "image/png",
            "content-length": String(6 * 1024 * 1024),
          },
        }),
    ],
    [
      "the remote streams past the cap without declaring a length",
      async (): Promise<Response> =>
        imageResponse(new Uint8Array(6 * 1024 * 1024)),
    ],
    [
      "the remote redirects onto a private address",
      async (): Promise<Response> => {
        const response = imageResponse(PNG);
        Object.defineProperty(response, "url", {
          value: "https://169.254.169.254/latest/meta-data",
        });
        return response;
      },
    ],
  ])("serves the stale copy when %s", async (_label, fetch) => {
    await seedStaleCopy();
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const response = await handler(request(REMOTE));

    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(OLD_PNG);
    // A stale copy that claimed the full max age would sit in Chromium's cache
    // past the point where the disk layer could replace it.
    expect(response.headers.get("cache-control")).toBe("no-cache");
  });

  it("still serves the image when it cannot be written to disk", async () => {
    vi.spyOn(images, "set").mockRejectedValue(new Error("disk full"));
    const handler = createCachedImageHandler(
      images,
      async () => imageResponse(PNG),
      MAX_AGE_MS,
    );

    const response = await handler(request(REMOTE));

    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(PNG);
  });

  it("responds 400 to a URL outside the cache scheme without fetching", async () => {
    const fetch = vi.fn<FetchLike>(async () => imageResponse(PNG));
    const handler = createCachedImageHandler(images, fetch, MAX_AGE_MS);

    const response = await handler(
      new Request(
        "posthog-cache://images/?src=http%3A%2F%2Fexample.com%2Fa.png",
      ),
    );

    expect(response.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });
});
