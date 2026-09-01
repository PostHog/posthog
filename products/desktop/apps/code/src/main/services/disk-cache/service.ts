import { createHash, randomUUID } from "node:crypto";
import {
  mkdir,
  readdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
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

export interface DiskCacheNamespaceOptions {
  /** Total bytes the namespace may hold. Oldest entries go first once passed. */
  maxBytes?: number;
}

function isNotFound(error: unknown): boolean {
  return (error as NodeJS.ErrnoException | null)?.code === "ENOENT";
}

/**
 * A sidecar that parses but has the wrong shape must not pass. A missing
 * `storedAt` makes the staleness arithmetic NaN, which reads as fresh, so the
 * entry would never expire and never refresh.
 */
function parseSidecar(raw: string): DiskCacheSidecar {
  const parsed = JSON.parse(raw) as Partial<DiskCacheSidecar>;
  if (
    typeof parsed?.contentType !== "string" ||
    typeof parsed?.storedAt !== "number" ||
    !Number.isFinite(parsed.storedAt)
  ) {
    throw new Error("Malformed cache sidecar");
  }
  return { contentType: parsed.contentType, storedAt: parsed.storedAt };
}

export class DiskCache implements IDiskCache {
  private readonly now: () => number;

  constructor(private readonly options: DiskCacheOptions) {
    this.now = options.now ?? Date.now;
  }

  namespace(
    name: string,
    options: DiskCacheNamespaceOptions = {},
  ): DiskCacheNamespace {
    return new DiskCacheNamespace(
      join(this.options.rootDir, name),
      this.now,
      options.maxBytes,
    );
  }

  async clear(): Promise<void> {
    await rm(this.options.rootDir, { recursive: true, force: true });
  }
}

export class DiskCacheNamespace {
  constructor(
    private readonly dir: string,
    private readonly now: () => number,
    private readonly maxBytes?: number,
  ) {}

  async get(
    key: string,
    options: { maxAgeMs: number },
  ): Promise<DiskCacheEntry | null> {
    const base = this.pathFor(key);
    try {
      const sidecar = parseSidecar(await readFile(`${base}.json`, "utf8"));
      const bytes = await readFile(base);
      return {
        bytes,
        contentType: sidecar.contentType,
        stale: this.now() - sidecar.storedAt > options.maxAgeMs,
      };
    } catch (error) {
      if (!isNotFound(error)) {
        // Log the hashed on-disk path, not the raw key: a key can be a signed
        // URL, and this logger exports off-device. The path still points at the
        // exact file to inspect.
        log.warn("Dropping unreadable cache entry", { path: base, error });
        // Cleanup is best effort. A locked file or bad permissions must not
        // reject get(), or the caller loses its network fallback and the
        // image request hard-fails.
        await this.delete(key).catch((deleteError) => {
          log.warn("Could not delete unreadable cache entry", {
            path: base,
            error: deleteError,
          });
        });
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
    await this.evictOverBudget();
  }

  /**
   * Keeps the namespace under its byte budget, oldest first. Entries expire by
   * age on read but nothing removes them, so without this a caller that reaches
   * for many distinct keys grows the directory until the disk is full.
   */
  private async evictOverBudget(): Promise<void> {
    const budget = this.maxBytes;
    if (budget === undefined) return;

    try {
      const names = await readdir(this.dir);
      const sized = await Promise.all(
        names
          .filter((name) => !name.endsWith(".json") && !name.endsWith(".tmp"))
          .map(async (name) => ({
            name,
            bytes: (await stat(join(this.dir, name))).size,
          })),
      );

      let total = sized.reduce((sum, entry) => sum + entry.bytes, 0);
      if (total <= budget) return;

      // Ages come from the sidecars, so only read them once eviction is on:
      // every write would otherwise pay for the whole namespace.
      const entries = await Promise.all(
        sized.map(async (entry) => ({
          ...entry,
          storedAt: await this.storedAtOf(join(this.dir, entry.name)),
        })),
      );

      entries.sort((a, b) => a.storedAt - b.storedAt);
      for (const entry of entries) {
        if (total <= budget) break;
        const base = join(this.dir, entry.name);
        await Promise.all([
          rm(base, { force: true }),
          rm(`${base}.json`, { force: true }),
        ]);
        total -= entry.bytes;
      }
    } catch (error) {
      log.warn("Could not trim cache namespace", { dir: this.dir, error });
    }
  }

  /** Age from the sidecar. An entry with no readable sidecar is junk, so it goes first. */
  private async storedAtOf(base: string): Promise<number> {
    try {
      return parseSidecar(await readFile(`${base}.json`, "utf8")).storedAt;
    } catch {
      return Number.NEGATIVE_INFINITY;
    }
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
