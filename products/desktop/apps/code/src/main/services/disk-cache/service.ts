import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { logger } from "@main/utils/logger";
import type { IDiskCache } from "@posthog/platform/disk-cache";

const log = logger.scope("diskCache");

export interface DiskCacheEntry {
  bytes: Buffer;
  contentType: string;
  stale: boolean;
}

interface DiskCacheSidecar {
  contentType: string;
  storedAt: number;
}

export interface DiskCacheOptions {
  rootDir: string;
  now?: () => number;
}

function isNotFound(error: unknown): boolean {
  return (error as NodeJS.ErrnoException | null)?.code === "ENOENT";
}

export class DiskCache implements IDiskCache {
  private readonly now: () => number;

  constructor(private readonly options: DiskCacheOptions) {
    this.now = options.now ?? Date.now;
  }

  namespace(name: string): DiskCacheNamespace {
    return new DiskCacheNamespace(join(this.options.rootDir, name), this.now);
  }

  async clear(): Promise<void> {
    await rm(this.options.rootDir, { recursive: true, force: true });
  }
}

export class DiskCacheNamespace {
  constructor(
    private readonly dir: string,
    private readonly now: () => number,
  ) {}

  async get(
    key: string,
    options: { maxAgeMs: number },
  ): Promise<DiskCacheEntry | null> {
    const base = this.pathFor(key);
    try {
      const sidecar = JSON.parse(
        await readFile(`${base}.json`, "utf8"),
      ) as DiskCacheSidecar;
      const bytes = await readFile(base);
      return {
        bytes,
        contentType: sidecar.contentType,
        stale: this.now() - sidecar.storedAt > options.maxAgeMs,
      };
    } catch (error) {
      if (!isNotFound(error)) {
        log.warn("Dropping unreadable cache entry", { key, error });
        await this.delete(key);
      }
      return null;
    }
  }

  async set(
    key: string,
    bytes: Uint8Array,
    contentType: string,
  ): Promise<void> {
    const base = this.pathFor(key);
    const sidecar: DiskCacheSidecar = { contentType, storedAt: this.now() };
    await mkdir(this.dir, { recursive: true });
    await writeAtomic(base, bytes);
    await writeAtomic(`${base}.json`, JSON.stringify(sidecar));
  }

  async delete(key: string): Promise<void> {
    const base = this.pathFor(key);
    await Promise.all([
      rm(base, { force: true }),
      rm(`${base}.json`, { force: true }),
    ]);
  }

  private pathFor(key: string): string {
    return join(this.dir, createHash("sha256").update(key).digest("hex"));
  }
}

async function writeAtomic(
  path: string,
  contents: Uint8Array | string,
): Promise<void> {
  const tmp = `${path}.${randomUUID()}.tmp`;
  await writeFile(tmp, contents);
  await rename(tmp, path);
}
