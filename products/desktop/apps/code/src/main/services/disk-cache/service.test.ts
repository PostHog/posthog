import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DiskCache } from "./service";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

describe("DiskCache", () => {
  let rootDir: string;
  let now: number;

  beforeEach(async () => {
    rootDir = await mkdtemp(join(tmpdir(), "disk-cache-"));
    now = 1_000;
  });

  afterEach(async () => {
    await rm(rootDir, { recursive: true, force: true });
  });

  function makeCache(): DiskCache {
    return new DiskCache({ rootDir, now: () => now });
  }

  it("round-trips bytes and content type by key", async () => {
    const images = makeCache().namespace("images");
    await images.set("https://example.com/a.png", PNG, "image/png");

    const entry = await images.get("https://example.com/a.png", {
      maxAgeMs: 100,
    });

    expect(entry).not.toBeNull();
    expect(new Uint8Array(entry?.bytes ?? [])).toEqual(PNG);
    expect(entry?.contentType).toBe("image/png");
    expect(entry?.stale).toBe(false);
  });

  it("returns null for a key never stored", async () => {
    const images = makeCache().namespace("images");
    expect(await images.get("missing", { maxAgeMs: 100 })).toBeNull();
  });

  it.each([
    [50, false],
    [100, false],
    [101, true],
  ])(
    "after %d ms with a 100 ms max age, stale is %s",
    async (elapsedMs, stale) => {
      const images = makeCache().namespace("images");
      await images.set("key", PNG, "image/png");
      now += elapsedMs;

      const entry = await images.get("key", { maxAgeMs: 100 });
      expect(entry?.stale).toBe(stale);
    },
  );

  it.each([
    ["{not json", "unparseable"],
    // Parses, but a missing storedAt makes the staleness arithmetic NaN, which
    // reads as fresh — the entry would never expire and never refresh.
    ['{"contentType":"image/png"}', "missing storedAt"],
    ['{"storedAt":1000}', "missing contentType"],
  ])("drops an entry whose sidecar is %s (%s)", async (sidecar) => {
    const images = makeCache().namespace("images");
    await images.set("key", PNG, "image/png");
    const hash = createHash("sha256").update("key").digest("hex");
    await writeFile(join(rootDir, "images", `${hash}.json`), sidecar);

    expect(await images.get("key", { maxAgeMs: 100 })).toBeNull();
    expect(await readdir(join(rootDir, "images"))).toEqual([]);
  });

  it("returns null when an unreadable entry cannot be deleted", async () => {
    const images = makeCache().namespace("images");
    const hash = createHash("sha256").update("key").digest("hex");
    await mkdir(join(rootDir, "images"), { recursive: true });
    await writeFile(join(rootDir, "images", `${hash}.json`), "{not json");
    // A directory at the bytes path makes the cleanup rm reject, so deletion
    // fails after the unreadable sidecar. get() must still resolve to null.
    await mkdir(join(rootDir, "images", hash));

    expect(await images.get("key", { maxAgeMs: 100 })).toBeNull();
  });

  it("keeps namespaces apart under one key", async () => {
    const cache = makeCache();
    await cache.namespace("images").set("key", PNG, "image/png");

    expect(
      await cache.namespace("other").get("key", { maxAgeMs: 100 }),
    ).toBeNull();
  });

  it("evicts the oldest entries once the namespace passes its byte budget", async () => {
    const big = new Uint8Array(1024);
    const images = makeCache().namespace("images", { maxBytes: 2048 });

    for (const key of ["a", "b", "c"]) {
      await images.set(key, big, "image/png");
      now += 1;
    }

    expect(await images.get("a", { maxAgeMs: Infinity })).toBeNull();
    expect(await images.get("c", { maxAgeMs: Infinity })).not.toBeNull();
  });

  it("clear removes every namespace", async () => {
    const cache = makeCache();
    await cache.namespace("images").set("a", PNG, "image/png");
    await cache.namespace("other").set("b", PNG, "image/png");

    await cache.clear();

    expect(
      await cache.namespace("images").get("a", { maxAgeMs: 100 }),
    ).toBeNull();
    expect(
      await cache.namespace("other").get("b", { maxAgeMs: 100 }),
    ).toBeNull();
    await expect(readdir(rootDir)).rejects.toMatchObject({ code: "ENOENT" });
  });
});
